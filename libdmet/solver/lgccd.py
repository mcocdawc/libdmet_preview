#!/usr/bin/env python
# Copyright 2014-2020 The PySCF Developers. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Author: Zhi-Hao Cui <zhcui0408@gmail.com>
#

'''
Linearized generalized coupled cluster doubles
'''

import numpy as np
from pyscf import lib
from pyscf.cc import ccsd
from pyscf.cc import gccsd

#from libdmet.solver import gccd_intermediates as imd

einsum = gccsd.einsum

def update_amps(cc, t1, t2, eris):
    assert isinstance(eris, gccsd._PhysicistsERIs)
    nocc, nvir = t1.shape
    fock = eris.fock

    fov = fock[:nocc,nocc:]
    mo_e_o = eris.mo_energy[:nocc]
    mo_e_v = eris.mo_energy[nocc:] + cc.level_shift

    tau = t2
    Foo = np.array(fock[:nocc, :nocc], copy=True)
    #Fov = fock[:nocc, nocc:].copy()
    Fvv = np.array(fock[nocc:, nocc:], copy=True)

    # Move energy terms to the other side
    Fvv[np.diag_indices(nvir)] -= mo_e_v
    Foo[np.diag_indices(nocc)] -= mo_e_o

    # T1 equation
    t1new = np.zeros_like(t1)

    # T2 equation
    Ftmp = Fvv #- 0.5*einsum('mb,me->be', t1, Fov)
    tmp = einsum('ijae,be->ijab', t2, Ftmp)
    t2new = tmp - tmp.transpose(0,1,3,2)
    tmp = None

    Ftmp = Foo #+ 0.5*einsum('je,me->mj', t1, Fov)
    tmp = einsum('imab,mj->ijab', t2, Ftmp)
    t2new -= (tmp - tmp.transpose(1,0,2,3))
    tmp = None

    t2new += np.asarray(eris.oovv).conj()

    Woooo = np.asarray(eris.oooo)
    t2new += einsum('mnab,mnij->ijab', tau, Woooo * 0.5)
    Woooo = None

    Wvvvv = np.asarray(eris.vvvv)
    t2new += 0.5*einsum('ijef,abef->ijab', tau, Wvvvv)
    Wvvvv = None

    Wovvo = np.asarray(eris.ovvo)
    tmp = einsum('imae,mbej->ijab', t2, Wovvo)
    Wovvo = None
    tmp = tmp - tmp.transpose(1,0,2,3)
    tmp = tmp - tmp.transpose(0,1,3,2)
    t2new += tmp
    tmp = None

    eia = mo_e_o[:,None] - mo_e_v
    for i in range(nocc):
        t2new[i] /= lib.direct_sum('a, jb -> jab', eia[i], eia)

    return t1new, t2new

class LGCCD(gccsd.GCCSD):
    update_amps = update_amps

    def kernel(self, t1=None, t2=None, eris=None):
        nocc = self.nocc
        nvir = self.nmo - nocc
        t1 = np.zeros((nocc, nvir))
        ccsd.CCSD.kernel(self, t1, t2, eris)
        return self.e_corr, self.t1, self.t2

    def solve_lambda(self, t1=None, t2=None, l1=None, l2=None,
                     eris=None):
        from libdmet.solver import gccd_lambda
        if t1 is None: t1 = self.t1
        if t2 is None: t2 = self.t2
        if eris is None: eris = self.ao2mo(self.mo_coeff)
        nocc = self.nocc
        nvir = self.nmo - nocc
        l1 = t1 = np.zeros((nocc, nvir))

        self.converged_lambda, self.l1, self.l2 = \
                gccd_lambda.kernel(self, eris, t1, t2, l1, l2,
                                   max_cycle=self.max_cycle,
                                   tol=self.conv_tol_normt,
                                   verbose=self.verbose)
        return self.l1, self.l2

    def make_rdm1(self, t1=None, t2=None, l1=None, l2=None, ao_repr=False):
        '''Un-relaxed 1-particle density matrix in MO space'''
        from libdmet.solver import gccd_rdm
        nocc = self.nocc
        nvir = self.nmo - nocc
        l1 = t1 = np.zeros((nocc, nvir))

        if t2 is None: t2 = self.t2
        if l2 is None: l2 = self.l2
        if l2 is None: l2 = self.solve_lambda(t1, t2)[-1]

        return gccd_rdm.make_rdm1(self, t1, t2, l1, l2, ao_repr=ao_repr)

    def make_rdm2(self, t1=None, t2=None, l1=None, l2=None, ao_repr=False):
        '''2-particle density matrix in MO space.  The density matrix is
        stored as

        dm2[p,r,q,s] = <p^+ q^+ s r>
        '''
        from libdmet.solver import gccd_rdm
        nocc = self.nocc
        nvir = self.nmo - nocc
        l1 = t1 = np.zeros((nocc, nvir))
        if t2 is None: t2 = self.t2
        if l2 is None: l2 = self.l2
        if l2 is None: l2 = self.solve_lambda(t1, t2)

        return gccd_rdm.make_rdm2(self, t1, t2, l1, l2, ao_repr=ao_repr)

if __name__ == '__main__':
    from pyscf import gto, scf
    np.set_printoptions(3, linewidth=1000, suppress=True)

    mol = gto.Mole()
    mol.verbose = 5
    #mol.atom = [['H', (0.,   0., 0.)],
    #            ['H', (0.7430, 0., 0.)]]
    #mol.basis = 'aug-ccpvtz'
    mol.atom = [['H', (0.,   0., 0.)],
                ['F', (1.1, 0., 0.)]]
    mol.basis = 'ccpvdz'
    mol.cart = True
    mol.build()

    mf = scf.RHF(mol)
    mf.conv_tol = 1e-12
    mf.kernel()

    mf = scf.addons.convert_to_ghf(mf)
    #gcc = gccsd.GCCSD(mf)

    gcc = LGCCD(mf)
    gcc.conv_tol = 1e-11
    gcc.conv_tol_normt = 1e-8
    #method = 'lgmres'
    ecc, t1, t2 = gcc.kernel()
    print (gcc.e_tot)

    rdm1 = gcc.make_rdm1()
    print (rdm1)
    print (np.trace(rdm1))
