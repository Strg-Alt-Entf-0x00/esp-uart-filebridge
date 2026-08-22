cmake_minimum_required(VERSION 3.16)

# Point IDF_PATH if not set in environment
# set(IDF_PATH "C:/esp/v6.0.2/esp-idf")

# Add esp-uart-filebridge component from local path during development.
# After publishing to GitHub, replace with the managed_components approach.
set(EXTRA_COMPONENT_DIRS "${CMAKE_CURRENT_LIST_DIR}/../../..")

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(uart_filebridge_basic)
