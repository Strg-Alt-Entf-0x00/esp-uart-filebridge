cmake_minimum_required(VERSION 3.16)

# Only include the esp-uart-filebridge component, nothing else from parent dirs
list(APPEND EXTRA_COMPONENT_DIRS "${CMAKE_CURRENT_LIST_DIR}/../..")

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(uart_filebridge_basic)
