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
  def __init__(self,
      input_size,
      hidden_size,
      batch_first=False,
      forget_bias=1.0,
      dropout=0.0,
      zoneout=0.0):
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