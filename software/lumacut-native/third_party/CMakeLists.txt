include(FetchContent)
# Clipper2 (Boost Software License 1.0): polygon booleans and offsets for the editor and PCB.
FetchContent_Declare(clipper2
  GIT_REPOSITORY https://github.com/AngusJohnson/Clipper2.git
  GIT_TAG Clipper2_1.5.4
  GIT_SHALLOW TRUE
  SOURCE_SUBDIR CPP
)
set(CLIPPER2_UTILS OFF CACHE BOOL "" FORCE)
set(CLIPPER2_EXAMPLES OFF CACHE BOOL "" FORCE)
set(CLIPPER2_TESTS OFF CACHE BOOL "" FORCE)
set(CLIPPER2_USINGZ OFF CACHE STRING "" FORCE)
FetchContent_MakeAvailable(clipper2)
