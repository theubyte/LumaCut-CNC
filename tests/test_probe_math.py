import unittest
from tools.probe_math import Bounds, laser_xy_for_probe, raise_z_after_probe, planned_mesh_grid

class GeometryTest(unittest.TestCase):
    def setUp(self):
        self.bounds=Bounds(0,400,0,400)

    def test_xy_offset(self):
        self.assertEqual(laser_xy_for_probe(100,200,15,-8,self.bounds),(85,208))

    def test_xy_bounds(self):
        with self.assertRaises(ValueError):
            laser_xy_for_probe(2,50,15,0,self.bounds)

    def test_xy_probe_bounds(self):
        with self.assertRaises(ValueError):
            laser_xy_for_probe(399,50,-15,0,self.bounds)

    def test_z_focus(self):
        self.assertEqual(raise_z_after_probe(45,6),39)

    def test_invalid_focus(self):
        with self.assertRaises(ValueError):
            raise_z_after_probe(-2,6)

    def test_mesh_serpentine(self):
        points=planned_mesh_grid(25,20,125,120,3,2,15,-8,self.bounds)
        self.assertEqual(len(points),6)
        self.assertEqual(points[0],dict(sample_x=25,sample_y=20,laser_x=10,laser_y=28))
        self.assertEqual(points[3]["sample_x"],125)

    def test_nan(self):
        with self.assertRaises(ValueError):
            laser_xy_for_probe(float("nan"),20,5,5,self.bounds)

if __name__=="__main__":
    unittest.main()
