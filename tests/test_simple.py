
import unittest

from tests.function import function

def function2(x):
    if x % 2 == 0:
        print("even")
        return True
    else:
        print("odd")
        return False


class TestSimple(unittest.TestCase):

    def test_even0(self):
        self.assertEqual(function(0), True)

    def test_even2(self):
        self.assertEqual(function(2), True)

    def test_odd(self):
        self.assertEqual(function(3), False)

    def test_evenodd(self):
        self.assertEqual(function(2), True)
        self.assertEqual(function(3), False)


    def test_even0_(self):
        self.assertEqual(function2(0), True)

    def test_even2_(self):
        self.assertEqual(function2(2), True)
