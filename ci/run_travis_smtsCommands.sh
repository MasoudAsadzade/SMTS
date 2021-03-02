#!/bin/bash

set -ev
cd home/SMTS;
mkdir build;
cd build;
cmake -DCMAKE_BUILD_TYPE=${CMAKE_BUILD_TYPE} -DCMAKE_CXX_FLAGS="$FLAGS" -DUSE_READLINE:BOOL=${USE_READLINE} -DCMAKE_INSTALL_PREFIX=${INSTALL} ..;
make -j4
