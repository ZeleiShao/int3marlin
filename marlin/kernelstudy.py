import unittest

import numpy as np
import torch
import torch.nn as nn

import marlin


seed = 16
np.random.seed(seed)
torch.random.manual_seed(seed)

DEV = torch.device('cuda:0')

def gen_quant3(m, n, groupsize=64, tile_shape=0):
    maxq = 2 ** 3 - 1
    w = torch.randn((m, n), dtype=torch.half, device=DEV)
    if groupsize != -1:
        w = w.reshape((-1, groupsize, n))
        w = w.permute(1, 0, 2)
        w = w.reshape((groupsize, -1))
    s = torch.max(torch.abs(w), 0, keepdim=True)[0]
    s *= 2 / maxq
    w = torch.round(w / s).int()
    z = torch.randn(s.shape, dtype=torch.half,device=DEV)
    w += (maxq + 1) // 2
    w = torch.clamp(w, 0, maxq)
    #ref = (w - (maxq + 1) // 2).half() * s
    ref = w.half() * s + z
    #ref = w
    def reshape(w):
        w = w.reshape((groupsize, -1, n))
        w = w.permute(1, 0, 2)
        w = w.reshape((m, n)).contiguous()
        return w
    ref = reshape(ref)

    s = s.reshape((-1, n)).contiguous()
    z = z.reshape((-1, n)).contiguous()
    linear = nn.Linear(m, n)
    linear.weight.data = ref.t()
    # Workaround to test some special cases that are forbidden by the API
    #layer = marlin.Layer3bitFaster(m, n, groupsize=groupsize)
    #layer = marlin.Layer3bit256_64(m, n, groupsize=groupsize)
    #layer = marlin.Layer3bit256_64_with_zero(m, n, groupsize=groupsize)
    #layer = marlin.Layer3bit_64_256_WithZero(m, n, groupsize=groupsize)
    #layer = marlin.Layer3bit(m, n, groupsize=groupsize)
    layer = marlin.Layer3bitWithZero(m, n, groupsize=groupsize)
    layer.k = m
    layer.n = n
    layer.groupsize = groupsize
    layer.B1 = torch.empty((m // 16, n * 16 * 2 // 32), dtype=torch.int, device=DEV)
    layer.B2 = torch.empty((m // 16, n * 16 // 32), dtype=torch.int, device=DEV)
    layer.s = torch.empty((m // groupsize, n), dtype=torch.half, device=DEV)
    layer.z = torch.empty((m // groupsize, n), dtype=torch.half, device=DEV)
    layer.pack(linear, s.t(), z.t())
    #layer.pack(linear, s.t())
    q1 = layer.B1
    q2 = layer.B2
    s = layer.s
    z = layer.z
    return ref, q1, q2, s, z

class Test(unittest.TestCase):
    def run_problem(self, m, n, k, thread_k, thread_n, groupsize=-1):  # 16, 512, 768, 64, 256
        print('% 5d % 6d % 6d % 4d % 4d % 4d' % (m, n, k, thread_k, thread_n, groupsize))
        A = torch.randn((m, k), dtype=torch.half, device=DEV)
        tile_shape = 0
        if k > n * 2 and k < 17000 and m <= 16:
            tile_shape = 1
        B_ref, B1, B2, s, z = gen_quant3(k, n, groupsize=groupsize,tile_shape=tile_shape)
        #z = torch.zeros(s.shape,dtype = torch.half, device=DEV)
        #B_ref, B1, B2, s = gen_quant4(k, n, groupsize=groupsize)
        #ref3, ref4, q4, q1, q2, s4, s3 = gen_quant4and3(m, n, groupsize=-1)
        C = torch.zeros((m, n), dtype=torch.half, device=DEV)
        C_ref = torch.matmul(A, B_ref)
        workspace = torch.zeros(n // 128 * 16, device=DEV)
        #marlin.mul_3bit(A, B1, B2, C, s, workspace, thread_k, thread_n, -1)
        #marlin.mul_3bit_256_64(A, B1, B2, C, s, workspace, thread_k, thread_n)
        #marlin.mul_3bit_256_64_with_zero(A, B1, B2, C, s, z,workspace, thread_k, thread_n)
        #marlin.mul_3bit_64_256_with_zero(A, B1, B2, C, s, z,workspace, 64,256)
        #marlin.mul_3bit_faster(A, B1, B2, C, s, workspace, thread_k, thread_n)
        marlin.mul_3bit_with_zero(A, B1, B2, C, s, z,workspace, thread_k, thread_n)
        torch.cuda.synchronize()
        b = torch.mean(torch.abs(C_ref))
        a = torch.mean(torch.abs(C - C_ref))
        #ratio = a / b
        #if a / b > 0.001 :
        #    print("error!!!! a:%.3f, b:%.3f, ratio:%.3f " % (a,b,ratio))

        self.assertLess(torch.mean(torch.abs(C - C_ref)) / torch.mean(torch.abs(C_ref)), 0.001)
        
    def test_tiles(self):
        for k in [3 * 64 + 64 * 4 * 2 + 64 * i for i in range(1,6,2)]:
            self.run_problem(16, 2 * 256, k, 64, 256)
                
    
if __name__ == '__main__':
    unittest.main()
