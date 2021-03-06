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

#include <Eigen/Dense>
#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <ctime>
#include <cuda.h>
#include <cuda_runtime_api.h>
#include <iostream>
#include <string>
#include <unsupported/Eigen/CXX11/Tensor>
#include <vector>

#include "device_ptr.h"
#include "haste.h"

using haste::v0::gru::ForwardPass;
using std::string;

using Tensor1 = Eigen::Tensor<float, 1>;
using Tensor2 = Eigen::Tensor<float, 2>;
using Tensor3 = Eigen::Tensor<float, 3>;

constexpr int BATCH_SIZE = 64;
constexpr int SEQUENCE_LEN = 1000;
constexpr int HIDDEN_DIMS = 512;
constexpr int INPUT_DIMS = 512;

static cublasHandle_t g_blas_handle;

class ScopeTimer {
  public:
    ScopeTimer(const string& msg) : msg_(msg) {
      cudaEventCreate(&start_);
      cudaEventCreate(&stop_);
      cudaDeviceSynchronize();
      cudaEventRecord(start_);
    }

    ~ScopeTimer() {
      float elapsed_ms;
      cudaEventRecord(stop_);
      cudaEventSynchronize(stop_);
      cudaEventElapsedTime(&elapsed_ms, start_, stop_);
      printf("%s %fms\n", msg_.c_str(), elapsed_ms);
      cudaEventDestroy(start_);
      cudaEventDestroy(stop_);
    }

  private:
    string msg_;
    cudaEvent_t start_, stop_;
};

void GruInference(const Tensor2& W, const Tensor2& R, const Tensor1& bx, const Tensor1& br, const Tensor3& x) {
  const int time_steps = x.dimension(2);
  const int batch_size = x.dimension(1);
  const int input_size = x.dimension(0);
  const int hidden_size = R.dimension(1);

  // Copy weights over to GPU.
  device_ptr<Tensor2> W_dev(W);
  device_ptr<Tensor2> R_dev(R);
  device_ptr<Tensor1> bx_dev(bx);
  device_ptr<Tensor1> br_dev(br);
  device_ptr<Tensor3> x_dev(x);

  device_ptr<Tensor2> h_dev(batch_size * hidden_size);
  device_ptr<Tensor3> tmp_Wx_dev(time_steps * batch_size * hidden_size * 3);
  device_ptr<Tensor2> tmp_Rh_dev(batch_size * hidden_size * 3);

  h_dev.zero();

  ScopeTimer t("Inference time:");
  ForwardPass<float> forward = ForwardPass<float>(
      false,  // training
      batch_size,
      input_size,
      hidden_size,
      g_blas_handle);

  for (int t = 0; t < time_steps; ++t) {
    const float* x_cur_dev = x_dev.data + t * batch_size * input_size;
    float* tmp_Wx_cur = tmp_Wx_dev.data + t * batch_size * hidden_size * 3;

    forward.Iterate(W_dev.data,
                    R_dev.data,
                    bx_dev.data,
                    br_dev.data,
                    x_cur_dev,
                    h_dev.data,
                    h_dev.data,
                    nullptr,  // v_out
                    tmp_Wx_cur,
                    tmp_Rh_dev.data,
                    0.0f,      // zoneout prob
                    nullptr);  // zoneout mask
  }
}

int main() {
  srand(time(0));

  cublasCreate(&g_blas_handle);

  // Weights.
  Tensor2 W(HIDDEN_DIMS * 3, INPUT_DIMS);
  Tensor2 R(HIDDEN_DIMS * 3, HIDDEN_DIMS);
  Tensor1 bx(HIDDEN_DIMS * 3);
  Tensor1 br(HIDDEN_DIMS * 3);

  // Input.
  Tensor3 x(INPUT_DIMS, BATCH_SIZE, SEQUENCE_LEN);

  W.setRandom();
  R.setRandom();
  bx.setRandom();
  br.setRandom();
  x.setRandom();

  GruInference(W, R, bx, br, x);

  cublasDestroy(g_blas_handle);

  return 0;
}
