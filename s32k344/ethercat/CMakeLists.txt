cmake_minimum_required(VERSION 3.20.0)

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(simantic_ecat_main)

# SOEM is fetched by scripts/setup/soem.sh (build.sh runs it) and passed in as SOEM_DIR.
file(GLOB SOEM_SOURCES ${SOEM_DIR}/soem/*.c)
target_sources(app PRIVATE src/main.c ${SOEM_SOURCES} ${SOEM_DIR}/osal/linux/osal.c
  ${SOEM_DIR}/oshw/linux/nicdrv.c ${SOEM_DIR}/oshw/linux/oshw.c)
target_include_directories(app PRIVATE ${SOEM_DIR}/soem ${SOEM_DIR}/osal ${SOEM_DIR}/osal/linux ${SOEM_DIR}/oshw/linux)
target_compile_options(app PRIVATE -Wno-unused-parameter -Wno-sign-compare -Wno-missing-field-initializers -Wno-pointer-sign)
