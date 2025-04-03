export ASAN_OPTIONS=detect_leaks=0 
export CFLAGS="${CFLAGS} -g -DFUZZING_OVERRIDE_LLVMFuzzerTestOneInput -fprofile-instr-generate -fcoverage-mapping "
export CC=clang 
./bootstrap.sh
./configure --enable-libfuzzer --enable-address-sanitizer --enable-static --enable-static-bin --disable-fabricd --disable-pbrd
make -j$(nproc) 
sudo make install