# Copyright 2020 LMNT, Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================

"""Layer Normalized Long Short-Term Memory"""


import haste_pytorch_lib as LIB
import torch
import torch.nn as nn
import torch.nn.functional as F


__all__ = [
    'LayerNormLSTM'
]


class LayerNormLSTMFunction(torch.autograd.Function):
  @staticmethod
  def forward(ctx, training, zoneout_prob, *inputs):
    outputs = LIB.layer_norm_lstm_forward(training, zoneout_prob, *inputs)
    ctx.save_for_backward(*inputs, *outputs)
    ctx.mark_non_differentiable(inputs[-1])  # zoneout mask is non-differentiable
    ctx.training = training
    return outputs[0], outputs[1]

  @staticmethod
  def backward(ctx, grad_h, grad_c):
    if not ctx.training:
      raise RuntimeError('LayerNormLSTM backward can only be called in training mode')

    saved = [*ctx.saved_tensors]
    saved[0] = saved[0].permute(2, 0, 1).contiguous()  # x -> x_t
    saved[1] = saved[1].permute(1, 0).contiguous()     # kernel -> kernel_t
    saved[2] = saved[2].permute(1, 0).contiguous()     # recurrent_kernel -> recurrent_kernel_t
    grads = LIB.layer_norm_lstm_backward(*saved, grad_h.contiguous(), grad_c.contiguous())
    return (None, None, *grads, None)


class LayerNormLSTM(nn.Module):
  """
  Layer Normalized Long Short-Term Memory layer.

  This LSTM layer applies layer normalization to the input, recurrent, and
  output activations of a standard LSTM. The implementation is fused and
  GPU-accelerated. DropConnect and Zoneout regularization are built-in, and
  this layer allows setting a non-zero initial forget gate bias.

  Details about the exact function this layer implements can be found at
  https://github.com/lmnt-com/haste/issues/1.

  See [\_\_init\_\_](#__init__) and [forward](#forward) for usage.
  """

  def __init__(self,
      input_size,
      hidden_size,
      batch_first=False,
      forget_bias=1.0,
      dropout=0.0,
      zoneout=0.0):
    """
    Initialize the parameters of the LSTM layer.

    Arguments:
      input_size: int, the feature dimension of the input.
      hidden_size: int, the feature dimension of the output.
      batch_first: (optional) bool, if `True`, then the input and output
        tensors are provided as `(batch, seq, feature)`.
      forget_bias: (optional) float, sets the initial bias of the forget gate
        for this LSTM cell.
      dropout: (optional) float, sets the dropout rate for DropConnect
        regularization on the recurrent matrix.
      zoneout: (optional) float, sets the zoneout rate for Zoneout
        regularization.

    Variables:
      kernel: the input projection weight matrix. Dimensions
        (input_size, hidden_size * 4) with `i,g,f,o` gate layout. Initialized
        with Xavier uniform initialization.
      recurrent_kernel: the recurrent projection weight matrix. Dimensions
        (hidden_size, hidden_size * 4) with `i,g,f,o` gate layout. Initialized
        with orthogonal initialization.
      bias: the projection bias vector. Dimensions (hidden_size * 4) with
        `i,g,f,o` gate layout. The forget gate biases are initialized to
        `forget_bias` and the rest are zeros.
      gamma: the input and recurrent normalization gain. Dimensions
        (2, hidden_size * 4) with `gamma[0]` specifying the input gain and
        `gamma[1]` specifying the recurrent gain. Initialized to ones.
      gamma_h: the output normalization gain. Dimensions (hidden_size).
        Initialized to ones.
      beta_h: the output normalization bias. Dimensions (hidden_size).
        Initialized to zeros.
    """
    super(LayerNormLSTM, self).__init__()

    if dropout < 0 or dropout > 1:
      raise ValueError('LayerNormLSTM: dropout must be in [0.0, 1.0]')
    if zoneout < 0 or zoneout > 1:
      raise ValueError('LayerNormLSTM: zoneout must be in [0.0, 1.0]')

    self.input_size = input_size
    self.hidden_size = hidden_size
    self.batch_first = batch_first
    self.forget_bias = forget_bias
    self.dropout = dropout
    self.zoneout = zoneout

    gpu = torch.device('cuda')
    self.kernel = nn.Parameter(torch.empty(input_size, hidden_size * 4, device=gpu))
    self.recurrent_kernel = nn.Parameter(torch.empty(hidden_size, hidden_size * 4, device=gpu))
    self.bias = nn.Parameter(torch.empty(hidden_size * 4, device=gpu))
    self.gamma = nn.Parameter(torch.empty(2, hidden_size * 4, device=gpu))
    self.gamma_h = nn.Parameter(torch.empty(hidden_size, device=gpu))
    self.beta_h = nn.Parameter(torch.empty(hidden_size, device=gpu))
    self.reset_parameters()

  def reset_parameters(self):
    """Resets this layer's parameters to their initial values."""
    hidden_size = self.hidden_size
    for i in range(4):
      nn.init.xavier_uniform_(self.kernel[:, i*hidden_size:(i+1)*hidden_size])
      nn.init.orthogonal_(self.recurrent_kernel[:, i*hidden_size:(i+1)*hidden_size])
    nn.init.zeros_(self.bias)
    nn.init.constant_(self.bias[hidden_size*2:hidden_size*3], self.forget_bias)
    nn.init.ones_(self.gamma)
    nn.init.ones_(self.gamma_h)
    nn.init.zeros_(self.beta_h)

  def forward(self, input, lengths=None):
    """
    Runs a forward pass of the LSTM layer.

    Arguments:
      input: Tensor, a batch of input sequences to pass through the LSTM.
        Dimensions (seq_len, batch_size, input_size) if `batch_first` is
        `False`, otherwise (batch_size, seq_len, input_size).
      lengths: (optional) Tensor, list of sequence lengths for each batch
        element. Dimension (batch_size). This argument may be omitted if
        all batch elements are unpadded and have the same sequence length.

    Returns:
      output: Tensor, the output of the LSTM layer. Dimensions
        (seq_len, batch_size, hidden_size) if `batch_first` is `False` (default)
        or (batch_size, seq_len, hidden_size) if `batch_first` is `True`. Note
        that if `lengths` was specified, the `output` tensor will not be
        masked. It's the caller's responsibility to either not use the invalid
        entries or to mask them out before using them.
      (h_n, c_n): the hidden and cell states, respectively, for the last
        sequence item. Dimensions (1, batch_size, hidden_size).
    """
    if self.batch_first:
      input = input.permute(1, 0, 2)

    if self.zoneout:
      zoneout_mask = torch.empty(
          input.shape[0],
          input.shape[1],
          self.hidden_size,
          dtype=input.dtype,
          device=input.device)
      zoneout_mask.bernoulli_(1.0 - self.zoneout)
    else:
      zoneout_mask = torch.empty(0, dtype=input.dtype, device=input.device)
    h, c = LayerNormLSTMFunction.apply(
        self.training,
        self.zoneout,
        input.contiguous(),
        self.kernel.contiguous(),
        F.dropout(self.recurrent_kernel, self.dropout, self.training).contiguous(),
        self.bias.contiguous(),
        self.gamma.contiguous(),
        self.gamma_h.contiguous(),
        self.beta_h.contiguous(),
        zoneout_mask.contiguous())

    if lengths is not None:
      cols = range(h.size(1))
      state = (h[[lengths, cols]].unsqueeze(0), c[[lengths, cols]].unsqueeze(0))
    else:
      state = (h[-1].unsqueeze(0), c[-1].unsqueeze(0))

    output = h[1:]
    if self.batch_first:
      output = output.permute(1, 0, 2)

    return output, state
