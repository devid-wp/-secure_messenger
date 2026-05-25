cmake_minimum_required(VERSION 3.15)
project(secure_core LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -O2 -Wall -Wextra")

include(FetchContent)
FetchContent_Declare(
  pybind11
  GIT_REPOSITORY https://github.com/pybind/pybind11.git
  GIT_TAG        v2.12.2
)
FetchContent_MakeAvailable(pybind11)

find_package(OpenSSL REQUIRED)

add_library(secure_core SHARED
  src/auth.cpp
  src/crypto.cpp
)

target_include_directories(secure_core
  PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include
)

target_link_libraries(secure_core
  PRIVATE OpenSSL::SSL OpenSSL::Crypto
)

if(TARGET pybind11::module)
  target_link_libraries(secure_core PRIVATE pybind11::module)
endif()

pybind11_add_module(crypto_core ../bindings/crypto_module.cpp)
target_link_libraries(crypto_core PRIVATE secure_core OpenSSL::SSL OpenSSL::Crypto)
target_include_directories(crypto_core PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include)

pybind11_add_module(auth_core ../bindings/auth_module.cpp)
target_link_libraries(auth_core PRIVATE secure_core OpenSSL::SSL OpenSSL::Crypto)
target_include_directories(auth_core PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include)
