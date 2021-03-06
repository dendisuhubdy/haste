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

import sys

from setuptools import setup
from setuptools.dist import Distribution


VERSION = '0.3.0'
DESCRIPTION = 'Haste: a fast, simple, and open RNN library.'
AUTHOR = 'LMNT, Inc.'
AUTHOR_EMAIL = 'haste@lmnt.com'
URL = 'https://www.lmnt.com'
LICENSE = 'Apache 2.0'
CLASSIFIERS = [
  'Development Status :: 4 - Beta',
  'Intended Audience :: Developers',
  'Intended Audience :: Education',
  'Intended Audience :: Science/Research',
  'License :: OSI Approved :: Apache Software License',
  'Programming Language :: Python :: 2.7',
  'Programming Language :: Python :: 3.4',
  'Programming Language :: Python :: 3.5',
  'Programming Language :: Python :: 3.6',
  'Topic :: Scientific/Engineering :: Mathematics',
  'Topic :: Software Development :: Libraries :: Python Modules',
  'Topic :: Software Development :: Libraries',
]


class BinaryDistribution(Distribution):
  """This class is needed in order to create OS specific wheels."""

  def has_ext_modules(self):
    return True


if sys.argv[1] == 'haste_tf':
  del sys.argv[1]
  setup(name = 'haste_tf',
      version = VERSION,
      description = DESCRIPTION,
      author = AUTHOR,
      author_email = AUTHOR_EMAIL,
      url = URL,
      license = LICENSE,
      keywords = 'tensorflow machine learning rnn lstm gru custom op',
      packages = ['haste_tf'],
      package_dir = { 'haste_tf': 'tf' },
      package_data = { 'haste_tf': ['*.so'] },
      install_requires = [],
      zip_safe = False,
      distclass = BinaryDistribution,
      classifiers = CLASSIFIERS)
elif sys.argv[1] == 'haste_pytorch':
  del sys.argv[1]
  from glob import glob
  from torch.utils import cpp_extension
  extension = cpp_extension.CppExtension(
      'haste_pytorch_lib',
      sources = glob('pytorch/*.cc'),
      include_dirs = ['lib', '/usr/local/cuda/include'],
      libraries = ['haste'],
      library_dirs = ['.'])
  setup(name = 'haste_pytorch',
      version = VERSION,
      description = DESCRIPTION,
      author = AUTHOR,
      author_email = AUTHOR_EMAIL,
      url = URL,
      license = LICENSE,
      keywords = 'pytorch machine learning rnn lstm gru custom op',
      packages = ['haste_pytorch'],
      package_dir = { 'haste_pytorch': 'pytorch' },
      install_requires = [],
      ext_modules = [extension],
      cmdclass = { 'build_ext': cpp_extension.BuildExtension },
      classifiers = CLASSIFIERS)
