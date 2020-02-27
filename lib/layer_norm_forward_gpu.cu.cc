// Copyright 2020 LMNT, Inc. All Rights Reserved.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//    http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.
// ==============================================================================

#include "haste.h"

namespace {

template<typename T>
__global__
void LayerNorm(
    const int batch_size,
    const int hidden_size,
    const T* alpha,
    const T* beta,
    const T* x,
    T* y,
    T* cache) {
  const int batch = blockDim.x * blockIdx.x + threadIdx.x;
  if (batch >= batch_size)
    return;

  extern __shared__ int shared_var[];
  T* shared = reinterpret_cast<T*>(shared_var);
  const int index = threadIdx.y;
  const int stride = blockDim.y;
  const int batch_idx = batch * hidden_size;
  const int batch_block_idx = threadIdx.x * stride;

  // TODO: use parallel single-pass algorithm to compute moments.

  // Reduce sum
  T sum = static_cast<T>(0.0);
  for (int i = index; i < hidden_size; i += stride)
    sum += x[batch_idx + i];
  shared[batch_block_idx + index] = sum;
  __syncthreads();

  for (int s = stride / 2; s > 0; s >>= 1) {
    if (index < s)
      shared[batch_block_idx + index] += shared[batch_block_idx + index + s];
    __syncthreads();
  }

  // Make sure this read completes before we start writing to `shared` again below.
  const T mean = shared[batch_block_idx] / hidden_size;
  __syncthreads();

  // Reduce squared difference
  T sumsq = static_cast<T>(0.0);
  for (int i = index; i < hidden_size; i += stride) {
    const T diff = x[batch_idx + i] - mean;
    sumsq += diff * diff;
  }
  shared[batch_block_idx + index] = sumsq;
  __syncthreads();

  for (int s = stride / 2; s > 0; s >>= 1) {
    if (index < s)
      shared[batch_block_idx + index] += shared[batch_block_idx + index + s];
    __syncthreads();
  }

  const T invstd = rsqrt(shared[batch_block_idx] / hidden_size + static_cast<T>(1e-5));

  for (int i = index; i < hidden_size; i += stride)
    y[batch_idx + i] = (x[batch_idx + i] - mean) * invstd * alpha[i] + beta[i];

  cache[batch * 2 + 0] = mean;
  cache[batch * 2 + 1] = invstd;
}

}  // anonymous namespace

namespace haste {
namespace v0 {
namespace layer_norm {

template<typename T>
ForwardPass<T>::ForwardPass(const int batch_size, const int hidden_size)
    : batch_size_(batch_size),
      hidden_size_(hidden_size) {
}

template<typename T>
void ForwardPass<T>::Run(
    const cudaStream_t& stream,
    const T* alpha,
    const T* beta,
    const T* x,
    T* y,
    T* cache) {
  dim3 blockDim(4, 256);
  dim3 gridDim;
  gridDim.x = (batch_size_ + blockDim.x - 1) / blockDim.x;
  const int shared_mem_size = sizeof(T) * blockDim.x * blockDim.y;
  LayerNorm<T><<<gridDim, blockDim, shared_mem_size, stream>>>(
      batch_size_,
      hidden_size_,
      alpha,
      beta,
      x,
      y,
      cache);
}

template class ForwardPass<float>;
template class ForwardPass<double>;

}  // namespace layer_norm
}  // namespace v0
}  // namespace haste