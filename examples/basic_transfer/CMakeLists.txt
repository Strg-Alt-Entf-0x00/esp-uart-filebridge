cmake_minimum_required(VERSION 3.16)

# Include the esp-uart-filebridge component from the repository
list(APPEND EXTRA_COMPONENT_DIRS "${CMAKE_CURRENT_LIST_DIR}/../../components")

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(uart_filebridge_basic)
