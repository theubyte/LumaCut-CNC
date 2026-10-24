"""Compile and exercise the same offset/raster geometry used by the ESP32 HMI."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
HEADER=ROOT/"firmware/hmi/src/probe_grid.h"


class GridGeometryTests(unittest.TestCase):
    def test_grid_math_compiles_and_never_moves_carriage_out_of_bounds(self):
        if not shutil.which("g++"):
            self.skipTest("g++ unavailable")
        cpp=r'''
#include <cassert>
#include <cmath>
#include "probe_grid.h"
using namespace LumaProbe;
int main(){
    Plan p{};
    Region r{0,0,100,50,10,15,-8};
    assert(clip(r,100,100,.5f,p));
    assert(p.clipped);
    assert(p.x0>=15.5f && p.x1<=100.0f);
    assert(p.y0>=0.0f && p.y1<=50.0f);
    float sx,sy,lx,ly;
    for(uint32_t i=0;i<(uint32_t)((uint64_t)p.nx*p.ny);i++){
        assert(point(r,p,i,sx,sy,lx,ly));
        assert(lx>=.5f-1e-3 && lx<=99.5f+1e-3);
        assert(ly>=.5f-1e-3 && ly<=99.5f+1e-3);
        assert(std::fabs((lx+15)-sx)<.0001f);
        assert(std::fabs((ly-8)-sy)<.0001f);
    }
    Region impossible{0,0,4,4,1,50,0};
    assert(!clip(impossible,40,40,.5f,p));
    Region dense{10,10,20,10,.5f,0,0};
    assert(clip(dense,200,200,.5f,p));
    assert(p.nx==41 && p.ny==21);
    for(uint32_t i=0;i<((uint64_t)p.nx*p.ny);i++)
        assert(point(dense,p,i,sx,sy,lx,ly));
    assert(!point(dense,p,(uint32_t)((uint64_t)p.nx*p.ny),sx,sy,lx,ly));
    return 0;
}'''
        with tempfile.TemporaryDirectory() as td:
            source=Path(td)/"grid.cpp"
            exe=Path(td)/"grid"
            source.write_text(cpp,encoding="utf-8")
            build=subprocess.run(["g++","-std=c++11","-Wall","-Wextra","-Werror",
                                  "-I",str(HEADER.parent),str(source),"-o",str(exe)],
                                 capture_output=True,text=True)
            self.assertEqual(build.returncode,0,build.stderr)
            subprocess.run([str(exe)],check=True)


if __name__=="__main__":
    unittest.main()
