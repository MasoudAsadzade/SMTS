#!/bin/bash

set -ev
git clone https://github.com/usi-verification-and-security/opensmt.git --branch v2.0.1 --single-branch
cd opensmt
mkdir build 
cd build
cmake -DCMAKE_INSTALL_PREFIX=SMTS/opensmt/build/SMTS/opensmt ..
make -j4
make install
