cmake_minimum_required(VERSION 3.16)

# Include the repository root, which is the canonical managed component.
list(APPEND EXTRA_COMPONENT_DIRS "${CMAKE_CURRENT_LIST_DIR}/../..")

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(uart_filebridge_basic)
