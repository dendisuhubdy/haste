AR ?= ar
CXX ?= g++
NVCC ?= nvcc
PYTHON ?= python

LOCAL_CFLAGS := -I/usr/include/eigen3 -I/usr/local/cuda/include -Ilib -O3
LOCAL_LDFLAGS := -L/usr/local/cuda/lib64 -L. -lcudart -lcublas

# Small enough project that we can just recompile all the time.
.PHONY: all haste haste_tf haste_pytorch examples benchmarks clean

all: haste haste_tf haste_pytorch examples benchmarks

haste:
	$(NVCC) -std=c++11 -arch=sm_60 -c lib/lstm_forward_gpu.cu.cc -o lib/lstm_forward_gpu.o -x cu -Xcompiler -fPIC $(LOCAL_CFLAGS)
	$(NVCC) -std=c++11 -arch=sm_60 -c lib/lstm_backward_gpu.cu.cc -o lib/lstm_backward_gpu.o -x cu -Xcompiler -fPIC $(LOCAL_CFLAGS)
	$(NVCC) -std=c++11 -arch=sm_60 -c lib/gru_forward_gpu.cu.cc -o lib/gru_forward_gpu.o -x cu -Xcompiler -fPIC $(LOCAL_CFLAGS)
	$(NVCC) -std=c++11 -arch=sm_60 -c lib/gru_backward_gpu.cu.cc -o lib/gru_backward_gpu.o -x cu -Xcompiler -fPIC $(LOCAL_CFLAGS)
	$(NVCC) -std=c++11 -arch=sm_60 -c lib/layer_norm_forward_gpu.cu.cc -o lib/layer_norm_forward_gpu.o -x cu -Xcompiler -fPIC $(LOCAL_CFLAGS)
	$(NVCC) -std=c++11 -arch=sm_60 -c lib/layer_norm_backward_gpu.cu.cc -o lib/layer_norm_backward_gpu.o -x cu -Xcompiler -fPIC $(LOCAL_CFLAGS)
	$(NVCC) -std=c++11 -arch=sm_60 -c lib/layer_norm_lstm_forward_gpu.cu.cc -o lib/layer_norm_lstm_forward_gpu.o -x cu -Xcompiler -fPIC $(LOCAL_CFLAGS)
	$(NVCC) -std=c++11 -arch=sm_60 -c lib/layer_norm_lstm_backward_gpu.cu.cc -o lib/layer_norm_lstm_backward_gpu.o -x cu -Xcompiler -fPIC $(LOCAL_CFLAGS)
	$(AR) -crv libhaste.a lib/*.o

haste_tf: haste
	$(eval TF_CFLAGS := $(shell $(PYTHON) -c 'import tensorflow as tf; print(" ".join(tf.sysconfig.get_compile_flags()))'))
	$(eval TF_LDFLAGS := $(shell $(PYTHON) -c 'import tensorflow as tf; print(" ".join(tf.sysconfig.get_link_flags()))'))
	$(CXX) -std=c++11 -c frameworks/tf/lstm.cc -o frameworks/tf/lstm.o $(LOCAL_CFLAGS) $(TF_CFLAGS) -fPIC
	$(CXX) -std=c++11 -c frameworks/tf/gru.cc -o frameworks/tf/gru.o $(LOCAL_CFLAGS) $(TF_CFLAGS) -fPIC
	$(CXX) -std=c++11 -c frameworks/tf/layer_norm.cc -o frameworks/tf/layer_norm.o $(LOCAL_CFLAGS) $(TF_CFLAGS) -fPIC
	$(CXX) -std=c++11 -c frameworks/tf/layer_norm_lstm.cc -o frameworks/tf/layer_norm_lstm.o $(LOCAL_CFLAGS) $(TF_CFLAGS) -fPIC
	$(CXX) -std=c++11 -c frameworks/tf/support.cc -o frameworks/tf/support.o $(LOCAL_CFLAGS) $(TF_CFLAGS) -fPIC
	$(CXX) -shared frameworks/tf/*.o libhaste.a -o frameworks/tf/libhaste_tf.so $(LOCAL_LDFLAGS) $(TF_LDFLAGS) -fPIC
	@$(eval TMP := $(shell mktemp -d))
	@cp -r frameworks/tf $(TMP)
	@cp setup.py $(TMP)
	@(cd $(TMP); $(PYTHON) setup.py haste_tf -q bdist_wheel)
	@cp $(TMP)/dist/*.whl .
	@rm -rf $(TMP)

haste_pytorch: haste
	@$(eval TMP := $(shell mktemp -d))
	@cp -r frameworks/pytorch $(TMP)
	@cp -r lib $(TMP)
	@cp setup.py $(TMP)
	@cp libhaste.a $(TMP)
	@(cd $(TMP); $(PYTHON) setup.py haste_pytorch -q bdist_wheel)
	@cp $(TMP)/dist/*.whl .
	@rm -rf $(TMP)

examples: haste
	$(CXX) -std=c++11 examples/lstm.cc libhaste.a $(LOCAL_CFLAGS) $(LOCAL_LDFLAGS) -o haste_lstm -Wno-ignored-attributes
	$(CXX) -std=c++11 examples/gru.cc libhaste.a $(LOCAL_CFLAGS) $(LOCAL_LDFLAGS) -o haste_gru -Wno-ignored-attributes

benchmarks: haste
	$(CXX) -std=c++11 benchmarks/benchmark_lstm.cc libhaste.a $(LOCAL_CFLAGS) $(LOCAL_LDFLAGS) -o benchmark_lstm -Wno-ignored-attributes -lcudnn

clean:
	rm -fr benchmark_lstm haste_lstm haste_gru build haste_*.whl
	find . \( -iname '*.o' -o -iname '*.so' -o -iname '*.a' \) -delete
