# -*- coding: utf-8 -*-
########################################################################################################################
#
# Copyright (c) 2014, Regents of the University of California
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without modification, are permitted provided that the
# following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this list of conditions and the following
#   disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the
#    following disclaimer in the documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES,
# INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
# WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#
########################################################################################################################

from __future__ import (absolute_import, division,
                        print_function, unicode_literals)
# noinspection PyUnresolvedReferences,PyCompatibility
from builtins import *

from abs_templates_ec.analog_mos.core import MOSTech

from typing import Dict, Any, Union, List, Optional
from itertools import chain
from collections import namedtuple

from bag.math import lcm
from bag.layout.util import BBox
from bag.layout.routing import RoutingGrid, WireArray, TrackID
from bag.layout.routing.fill import fill_symmetric_const_space
from bag.layout.template import TemplateBase

ExtInfo = namedtuple('ExtInfo', ['mx_margin', 'od_margin', 'md_margin', 'm1_margin', 'imp_min_w',
                                 'mtype', 'thres', 'po_types', 'edgel_info', 'edger_info'])
RowInfo = namedtuple('RowInfo', ['od_x_list', 'od_y', 'od_type', 'po_y', 'md_y'])
AdjRowInfo = namedtuple('AdjRowInfo', ['po_y', 'po_types'])
EdgeInfo = namedtuple('EdgeInfo', ['od_type'])
FillInfo = namedtuple('FillInfo', ['layer', 'exc_layer', 'x_intv_list', 'y_intv_list'])


def _to_warr(warr_list):
    if len(warr_list) == 1:
        return warr_list[0]

    layer = warr_list[0].track_id.layer_id
    lower, upper = warr_list[0].lower, warr_list[0].upper
    base_idx = warr_list[0].track_id.base_index
    pitch = warr_list[1].track_id.base_index - base_idx
    return WireArray(TrackID(layer, base_idx, num=len(warr_list), pitch=pitch), lower, upper)


class MOSTechTSMC16(MOSTech):
    tech_constants = dict(
        # layout unit length in meters
        layout_unit=1e-6,
        # layout resolution
        resolution=0.001,
        # fin height.
        fin_h=14,
        # fin pitch.
        fin_pitch=48,
        # space between MP and CPO
        mp_cpo_sp=19,
        # MP height
        mp_h=40,
        # MP and PO overlap
        mp_po_ovl=16,
        # space between MP and MD
        mp_md_sp=13,
        # vertical space between adjacent MP
        mp_spy=34,
        # MD width
        md_w=40,
        # MD space
        md_sp=46,
        # space between MD and OD
        md_od_spy=40,
        # extension of MD over OD
        md_od_exty=20,
        # minimum MD height
        md_h_min=68,
        # space between VIA0
        v0_sp=32,
        # space between VIA1X
        vx_sp=42,
        # CPO height
        cpo_h=60,
        # space between CPO and OD
        cpo_od_sp=20,
        # minimum CPO vertical space
        cpo_spy=90,
        # enclosure of CPO over PO
        cpo_po_ency=34,
        # maximum space between OD in fin pitch.
        od_sp_nfin_max=16,
        # minimum number of fins in OD
        od_nfin_min=2,
        # maximum number of fins in OD
        od_nfin_max=20,
        # minimum number of fingers for dummy OD
        dum_od_fg_min=2,
        # finger space between dummy OD
        dum_od_fg_space=2,
        # vertical enclosure of PP/NP/NW over OD
        imp_od_ency=45,
        # horizontal enclosure of PP/NP/NW over OD
        imp_od_encx=65,
        # minimum PP/NP width.
        imp_wmin=52,
        # minimum M1X area
        mx_area_min=6176,
        # maximum space between metal 1.
        m1_sp_max=1600,
        # space between metal 1 and boundary.
        m1_sp_bnd=800,
        # metal 1 fill minimum length
        m1_fill_lmin=200,
        # metal 1 fill maximum length
        m1_fill_lmax=400,
        # minimum M1X line-end spacing
        mx_spy_min=64,
    )

    @classmethod
    def get_mos_layers(cls, mos_type, threshold):
        """Returns a list of implant/well/threshold layers.

        Parameters
        ----------
        mos_type : str
            the transistor type.  Valid values are 'pch', 'nch', 'ntap', and 'ptap'.
        threshold : str
            the threshold flavor.

        Returns
        -------
        layer_list : list[Tuple[str, str]]
            a list of implant/well/threshold layer names.
        """
        lay_list = [('FinArea', 'fin48')]
        if mos_type == 'pch' or mos_type == 'ntap':
            lay_list.append(('NWell', 'drawing'))

        mtype = 'P' if mos_type == 'pch' or mos_type == 'ptap' else 'N'

        if threshold == 'lvt' or threshold == 'fast':
            thres = '%slvt' % mtype
        elif threshold == 'svt' or threshold == 'standard':
            thres = '%ssvt' % mtype
        elif threshold == 'hvt' or threshold == 'low_power':
            thres = '%shvt' % mtype
        else:
            raise Exception('Unrecognized threshold %s' % threshold)

        lay_list.append((thres, 'drawing'))
        return lay_list

    @classmethod
    def get_gate_via_info(cls, lch_unit):
        # type: (int) -> Dict[str, Any]
        """Get gate via information"""
        via_info = dict(
            # gate via height
            h=[32, 32, 32],
            # gate via width
            w=[32, 32, 32],
            # bottom metal horizontal enclosure
            bot_encx=[18, 4, 40],
            # bottom metal vertical enclosure
            bot_ency=[4, 40, 0],
            # top metal horizontal enclosure
            top_encx=[4, 40, 4],
            # top metal vertical enclosure
            top_ency=[40, 0, 40],
        )

        mx_area_min = cls.tech_constants['mx_area_min']
        md_w = cls.tech_constants['md_w']

        v0_h, v1_h, v2_h = via_info['h']
        v0_m1_ency, v1_m2_ency, v2_m3_ency = via_info['top_ency']

        mx_h_min = -(-mx_area_min // md_w)  # type: int
        m1_h = max(v0_h + 2 * v0_m1_ency, mx_h_min)
        m2_h = v1_h + 2 * v1_m2_ency
        m3_h = max(v2_h + 2 * v2_m3_ency, mx_h_min)

        via_info['m1_h'] = m1_h
        via_info['m2_h'] = m2_h
        via_info['m3_h'] = m3_h

        return via_info

    @classmethod
    def get_ds_via_info(cls, lch_unit, w, compact=False):
        # type: (int, int) -> Dict[str, Any]
        """Get drain_source via information"""
        via_info = dict(
            # gate via height
            h=[32, 64, 64],
            # gate via width
            w=[32, 32, 32],
            # bottom metal horizontal enclosure
            bot_encx=[3, 4, 10],
            # bottom metal vertical enclosure
            bot_ency=[18, 20, 10],
            # top metal horizontal enclosure
            top_encx=[4, 10, 4],
            # top metal vertical enclosure
            top_ency=[40, 10, 20],
        )

        # compute number of V0s and height of various metals
        fin_h = cls.tech_constants['fin_h']
        fin_p = cls.tech_constants['fin_p']
        md_od_exty = cls.tech_constants['md_od_exty']
        md_h_min = cls.tech_constants['md_h_min']
        mx_area_min = cls.tech_constants['mx_area_min']
        v0_sp = cls.tech_constants['v0_sp']
        md_w = cls.tech_constants['md_w']
        vx_sp = cls.tech_constants['vx_sp']

        v0_h = via_info['h'][0]
        v0_md_ency = via_info['bot_ency'][0]
        v0_m1_ency = via_info['top_ency'][0]
        od_h = (w - 1) * fin_p + fin_h
        md_h = max(od_h + 2 * md_od_exty, md_h_min)
        num_v0 = (md_h - v0_md_ency * 2 - v0_sp) // (v0_sp + v0_h)

        # M1 height based on V0 enclosure
        v0_harr = num_v0 * (v0_h + v0_sp) - v0_sp
        m1_h = v0_harr + 2 * v0_m1_ency

        # M1 height based on the fact that we need to fit two M2 wires
        v1_h = via_info['h'][1]
        v1_m1_ency = via_info['bot_ency'][1]
        v1_m2_ency = via_info['top_ency'][1]
        m2_h = v1_h + 2 * v1_m2_ency
        m1_h = max(m1_h, 2 * v1_m1_ency + 2 * v1_h + vx_sp)

        # make sure M1 passes minimum area rule
        mx_h_min = -(-mx_area_min // md_w)  # type: int
        m1_h = max(m1_h, mx_h_min)

        # get M3 height
        v2_h = via_info['h'][2]
        v2_m3_ency = via_info['top_ency'][2]

        m3_h = max(v2_h + 2 * v2_m3_ency, mx_h_min)

        via_info['num_v0'] = num_v0
        via_info['md_h'] = md_h
        via_info['m1_h'] = m1_h
        via_info['m2_h'] = m2_h
        via_info['m3_h'] = m3_h

        return via_info

    @classmethod
    def get_edge_tech_constants(cls, lch_unit):

        imp_od_encx = cls.tech_constants['imp_od_encx']

        mos_constants = cls.get_mos_tech_constants(lch_unit)
        sd_pitch = mos_constants['sd_pitch']

        # calculate number of fingers needed around OD To satisfy implant enclosure rule
        od_fg_margin = -(-(imp_od_encx - (sd_pitch - lch_unit) // 2) // sd_pitch)

        constants = dict(
            gr_nf_min=2,
            outer_fg=3,
            gr_outer_fg=0,
            gr_sub_fg_margin=od_fg_margin,
            gr_sep_fg=od_fg_margin + 1,
        )

        constants['cpo_extx'] = 34

        return constants

    @classmethod
    def get_mos_tech_constants(cls, lch_unit):
        # type: (int) -> Dict[str, Any]
        if lch_unit == 18:
            constants = dict(
                sd_pitch=90,
            )
        else:
            raise ValueError('Unsupported channel length: %d' % lch_unit)

        constants['laygo_num_sd_per_track'] = constants['num_sd_per_track'] = 1

        # set MD related parameters
        md_w = cls.tech_constants['md_w']
        constants['laygo_conn_w'] = constants['mos_conn_w'] = constants['dum_conn_w'] = constants['m1_w'] = md_w
        return constants

    @classmethod
    def get_analog_unit_fg(cls):
        # type: () -> int
        return 2

    @classmethod
    def draw_zero_end_row(cls):
        return True

    @classmethod
    def draw_zero_extension(cls):
        return True

    @classmethod
    def get_dum_conn_pitch(cls):
        # type: () -> int
        return 1

    @classmethod
    def get_dum_conn_layer(cls):
        # type: () -> int
        return 1

    @classmethod
    def get_mos_conn_layer(cls):
        # type: () -> int
        return 3

    @classmethod
    def get_dig_conn_layer(cls):
        # type: () -> int
        return 1

    @classmethod
    def get_min_fg_decap(cls, lch_unit):
        # type: (int) -> int
        return 2

    @classmethod
    def get_tech_constant(cls, name):
        # type: (str) -> Any
        return cls.tech_constants[name]

    @classmethod
    def get_mos_pitch(cls, unit_mode=False):
        # type: (bool) -> Union[float, int]
        ans = cls.tech_constants['fin_pitch']
        if unit_mode:
            return ans
        return ans * cls.tech_constants['resolution']

    @classmethod
    def get_edge_info(cls, grid, lch_unit, guard_ring_nf, top_layer, is_end):
        # type: (RoutingGrid, int, int, int, bool) -> Dict[str, Any]

        edge_constants = cls.get_edge_tech_constants(lch_unit)
        cpo_extx = edge_constants['cpo_extx']
        gr_nf_min = edge_constants['gr_nf_min']
        outer_fg = edge_constants['outer_fg']
        gr_outer_fg = edge_constants['gr_outer_fg']
        gr_sub_fg_margin = edge_constants['gr_sub_fg_margin']
        gr_sep_fg = edge_constants['gr_sep_fg']

        mos_constants = cls.get_mos_tech_constants(lch_unit)
        sd_pitch = mos_constants['sd_pitch']

        if 0 < guard_ring_nf < gr_nf_min:
            raise ValueError('guard_ring_nf = %d < %d' % (guard_ring_nf, gr_nf_min))

        vm_pitch = grid.get_block_size(top_layer, unit_mode=True)[0]
        if is_end:
            # compute how much to shift to the right to make room
            # for implant layers enclosure, and also be fit in block pitch

            # compute CPO X coordinate, and whether we need to shift PO over by 1.
            left_margin = (sd_pitch - lch_unit) // 2
            max_encx = max(left_margin, cpo_extx)
            xshift = -(-(max_encx - left_margin) // vm_pitch) * vm_pitch
            cpo_xl = left_margin - cpo_extx + xshift
        else:
            xshift = cpo_xl = 0

        # compute total edge block width
        if guard_ring_nf == 0:
            fg_tot = outer_fg
            gr_sub_fg = 0
        else:
            outer_fg = gr_outer_fg
            gr_sub_fg = guard_ring_nf + 2 + 2 * gr_sub_fg_margin
            fg_tot = outer_fg + gr_sub_fg + gr_sep_fg

        return dict(
            edge_width=fg_tot * sd_pitch + xshift,
            dx_edge=xshift,
            cpo_xl=cpo_xl,
            outer_fg=outer_fg,
            gr_sub_fg=gr_sub_fg,
            gr_sep_fg=gr_sep_fg,
        )

    @classmethod
    def get_mos_info(cls, lch_unit, w, mos_type, threshold, fg, **kwargs):
        # type: (int, int, str, str, int, **kwargs) -> Dict[str, Any]
        """A single row of transistor, which enough margin to draw gate/drain via.

        Strategy:

        1. from CPO-M0PO spacing, get gate M0PO/M1 location
        #. get OD location such that:
           i. OD is in the center of drain/source M1 contact.
           #. gate-drain M1 spacing is satisfied.
        #. round OD location to fin grid, get M0OD/M1 coordinates.
        #. update gate M0PO/M1 location so that gate-drain M1 spacing equals minimum.
        #. find top CPO location from OD-CPO spacing.
        #. compute gate/drain/source M3 locations.
        #. compute extension information, then return layout information dictionary.
        """

        fin_h = cls.tech_constants['fin_h']
        fin_p = cls.tech_constants['fin_pitch']
        mp_cpo_sp = cls.tech_constants['mp_cpo_sp']
        cpo_od_sp = cls.tech_constants['cpo_od_sp']
        md_w = cls.tech_constants['md_w']
        cpo_h = cls.tech_constants['cpo_h']
        mp_h = cls.tech_constants['mp_h']
        mx_spy_min = cls.tech_constants['mx_spy_min']
        vx_sp = cls.tech_constants['vx_sp']

        mos_constants = cls.get_mos_tech_constants(lch_unit)
        sd_pitch = mos_constants['sd_pitch']
        m3_w = mos_constants['mos_conn_w']

        gate_via_info = cls.get_gate_via_info(lch_unit)
        gv0_h, gv1_h, gv2_h = gate_via_info['h']
        g_m1_ency, g_m2_ency, g_m3_ency = gate_via_info['top_ency']
        g_m1_h = gate_via_info['m1_h']
        g_m2_h = gate_via_info['m2_h']
        g_m3_h = gate_via_info['m3_h']

        ds_via_info = cls.get_ds_via_info(lch_unit, w)
        dv0_h, dv1_h, dv2_h = ds_via_info['h']
        ds_md_bot_ency, ds_m1_bot_ency, ds_m2_bot_ency = ds_via_info['bot_ency']
        d_m1_ency, d_m2_ency, d_m3_ency = ds_via_info['top_ency']
        md_h = ds_via_info['md_h']
        m1_h = ds_via_info['m1_h']
        m3_h = ds_via_info['m3_h']

        # step 1: place bottom CPO, compute gate/OD locations
        # step 1A: get CPO location
        blk_yb = 0
        cpo_bot_yb = blk_yb - cpo_h // 2
        cpo_bot_yt = cpo_bot_yb + cpo_h
        # step 1B: get gate via/M1 location
        mp_yb = cpo_bot_yt + mp_cpo_sp
        mp_yt = mp_yb + mp_h
        mp_yc = (mp_yt + mp_yb) // 2
        g_m1_yt = mp_yc + gv0_h // 2 + g_m1_ency
        # step 1C: get OD location, round to fin grid.
        od_yc = g_m1_yt + mx_spy_min + m1_h // 2
        if w % 2 == 0:
            od_yc = -(-od_yc // fin_p) * fin_p
        else:
            od_yc = -(-(od_yc - fin_p // 2) // fin_p) * fin_p + fin_p // 2
        # compute OD/MD/CMD location
        od_h = (w - 1) * fin_p + fin_h
        od_yb = od_yc - od_h // 2
        od_yt = od_yb + od_h
        md_yb = od_yc - md_h // 2
        md_yt = md_yb + md_h
        ds_m1_yb = od_yc - m1_h // 2
        ds_m1_yt = ds_m1_yb + m1_h
        # update gate location
        g_m1_yt = ds_m1_yb - mx_spy_min
        g_m1_yb = g_m1_yt - g_m1_h
        g_m1_yc = (g_m1_yb + g_m1_yt) // 2

        # step 2: compute top CPO location.
        blk_yt = od_yt + cpo_od_sp + cpo_h // 2
        blk_yt = -(-blk_yt // fin_p) * fin_p

        # step 3: compute gate M2/M3 locations
        g_m2_yt = g_m1_yc + gv1_h // 2 + g_m2_ency
        g_m2_yb = g_m2_yt - g_m2_h
        g_m2_yc = (g_m2_yb + g_m2_yt)
        g_m3_yt = g_m2_yc + g_m3_h // 2
        g_m3_yb = g_m3_yt - g_m3_h

        # step 4: compute drain/source M3 location when going up.  This is needed for metal 3 margin.
        d_v1_yc = ds_m1_yt - ds_m1_bot_ency - dv1_h // 2
        d_m3_yb = d_v1_yc - dv2_h // 2 - d_m3_ency
        d_m3_yt = d_m3_yb + m3_h

        s_v1_yc = ds_m1_yb + ds_m1_bot_ency + dv1_h // 2
        s_m3_yt = s_v1_yc + dv2_h // 2 + d_m3_ency
        s_m3_yb = s_m3_yt - m3_h

        # step 5: compute extension information
        lr_edge_info = EdgeInfo(od_type='mos')

        mtype = (mos_type, mos_type)
        po_types = (1,) * fg
        ext_top_info = ExtInfo(
            mx_margin=blk_yt - d_m3_yt,
            od_margin=blk_yt - od_yt,
            md_margin=blk_yt - md_yt,
            m1_margin=blk_yt - ds_m1_yt,
            imp_min_w=0,
            mtype=mtype,
            thres=threshold,
            po_types=po_types,
            edgel_info=lr_edge_info,
            edger_info=lr_edge_info,
        )
        ext_bot_info = ExtInfo(
            mx_margin=g_m3_yb - blk_yb,
            od_margin=od_yb - blk_yb,
            md_margin=md_yb - blk_yb,
            m1_margin=g_m1_yb - blk_yb,
            imp_min_w=0,
            mtype=mtype,
            thres=threshold,
            po_types=po_types,
            edgel_info=lr_edge_info,
            edger_info=lr_edge_info,
        )

        # step 6: compute layout information
        lay_info_list = []
        for lay in cls.get_mos_layers(mos_type, threshold):
            lay_info_list.append((lay, 0, blk_yb, blk_yt))

        sub_type = 'ptap' if mos_type == 'nch' else 'ntap'
        fill_info = FillInfo(layer=('M1', 'drawing'), exc_layer=None,
                             x_intv_list=[], y_intv_list=[(ds_m1_yb, ds_m1_yt)])
        layout_info = dict(
            # information needed for draw_mos
            lch_unit=lch_unit,
            md_w=md_w,
            fg=fg,
            sd_pitch=sd_pitch,
            array_box_xl=0,
            array_box_y=(blk_yb, blk_yt),
            draw_od=not kwargs.get('ds_dummy', False),
            row_info_list=[RowInfo(od_x_list=[(0, fg)],
                                   od_y=(od_yb, od_yt),
                                   od_type=('mos', sub_type),
                                   po_y=(blk_yb, blk_yt),
                                   md_y=(md_yb, md_yt)), ],
            lay_info_list=lay_info_list,
            adj_info_list=[],
            left_blk_info=None,
            right_blk_info=None,
            fill_info_list=[fill_info],

            # information needed for computing edge block layout
            blk_type='mos',
            imp_params=[(mos_type, threshold, blk_yb, blk_yt, blk_yb, blk_yt)],
        )

        # step 8: return results
        return dict(
            layout_info=layout_info,
            ext_top_info=ext_top_info,
            ext_bot_info=ext_bot_info,
            left_edge_info=(lr_edge_info, []),
            right_edge_info=(lr_edge_info, []),
            sd_yc=od_yc,
            g_conn_y=(g_m3_yb, g_m3_yt),
            d_conn_y=(d_m3_yb, d_m3_yt),
            s_conn_y=(s_m3_yb, s_m3_yt),
            g_loc=[[g_m1_yb, g_m1_yt], [g_m2_yb, g_m2_yt], [g_m3_yb, g_m3_yt]],
            m3_w=m3_w,
            sd_pitch=sd_pitch,
            num_sd_per_track=1,
        )

    @classmethod
    def get_valid_extension_widths(cls, lch_unit, top_ext_info, bot_ext_info):
        # type: (int, ExtInfo, ExtInfo) -> List[int]
        """Compute a list of valid extension widths.

        The DRC rules that we consider are:

        1. wire line-end space
        #. MD space
        # implant/threshold layers minimum width.
        #. CPO space
        #. max OD space
        #. lower metal fill
        #. implant/threshold layers to draw

        Of these rules, only the first three sets the minimum extension width.  However,
        if the maximum extension width with no dummy OD is smaller than 1 minus the minimum
        extension width with dummy OD, then that implies there exists some extension widths
        that need dummy OD but can't draw it.

        so our layout strategy is:

        1. compute minimum extension width from wire line-end/MD spaces/minimum implant width.
        #. Compute the maximum extension width that we don't need to draw dummy OD.
        #. Compute the minimum extension width that we can draw DRC clean dummy OD.
        #. Return the list of valid extension widths
        """
        fin_h = cls.tech_constants['fin_h']  # type: int
        fin_p = cls.tech_constants['fin_pitch']  # type: int
        od_sp_nfin_max = cls.tech_constants['od_sp_nfin_max']
        od_nfin_min = cls.tech_constants['od_nfin_min']
        cpo_od_sp = cls.tech_constants['cpo_od_sp']  # type: int
        cpo_spy = cls.tech_constants['cpo_spy']
        md_od_exty = cls.tech_constants['md_od_exty']
        imp_od_ency = cls.tech_constants['imp_od_ency']
        mx_spy_min = cls.tech_constants['mx_spy_min']  # type: int
        md_sp = cls.tech_constants['md_sp']  # type: int
        cpo_h = cls.tech_constants['cpo_h']
        md_h_min = cls.tech_constants['md_h_min']

        fin_p2 = fin_p // 2
        fin_h2 = fin_h // 2

        bot_imp_min_w = bot_ext_info.imp_min_w  # type: int
        top_imp_min_w = top_ext_info.imp_min_w  # type: int

        # step 1: get minimum extension width
        mx_margin = top_ext_info.mx_margin + bot_ext_info.mx_margin  # type: int
        m1_margin = top_ext_info.m1_margin + bot_ext_info.m1_margin  # type: int
        min_ext_w = max(0, -(-(mx_spy_min - min(mx_margin, m1_margin)) // fin_p))
        md_margin = top_ext_info.md_margin + bot_ext_info.md_margin
        min_ext_w = max(min_ext_w, -(-(md_sp - md_margin) // fin_p), -(-(bot_imp_min_w + top_imp_min_w) // fin_p))

        # step 2: get maximum extension width without dummy OD
        od_space_nfin = (top_ext_info.od_margin + bot_ext_info.od_margin + fin_h) // fin_p
        max_ext_w_no_od = od_sp_nfin_max - od_space_nfin

        # step 3: find minimum extension width with dummy OD
        # now, the tricky part is that we need to make sure OD can be drawn in such a way
        # that we can satisfy both minimum implant width constraint and implant-OD enclosure
        # constraint.  Currently, we compute minimum size so we can split implant either above
        # or below OD and they'll both be DRC clean.  This is a little sub-optimal, but
        # makes layout algorithm much much easier.

        # get od_yb_max1, round to fin grid.
        dum_md_yb = -bot_ext_info.md_margin + md_sp
        od_yb_max1 = max(dum_md_yb + md_od_exty, cpo_h // 2 + cpo_od_sp)
        od_yb_max1 = -(-(od_yb_max1 - fin_p2 + fin_h2) // fin_p)
        # get od_yb_max2, round to fin grid.
        od_yb_max = bot_imp_min_w + imp_od_ency
        od_yb_max = max(od_yb_max1, -(-(od_yb_max - fin_p2 + fin_h2) // fin_p))

        # get od_yt_min1 assuming yt = 0, round to fin grid.
        dum_md_yt = top_ext_info.md_margin - md_sp
        od_yt_min1 = min(dum_md_yt - md_od_exty, -(cpo_h // 2) - cpo_od_sp)
        od_yt_min1 = (od_yt_min1 - fin_p2 - fin_h2) // fin_p
        # get od_yt_min2, round to fin grid.
        od_yt_min = -top_imp_min_w - imp_od_ency
        od_yt_min = min(od_yt_min1, (od_yt_min - fin_p2 - fin_h2) // fin_p)

        # get minimum extension width from OD related spacing rules
        min_ext_w_od = max(0, od_nfin_min - (od_yt_min - od_yb_max) - 1) * fin_p
        # check to see CPO spacing rule is satisfied
        min_ext_w_od = max(min_ext_w_od, cpo_spy + cpo_h)
        # check to see MD minimum height rule is satisfied
        min_ext_w_od = max(min_ext_w_od, md_h_min - (dum_md_yt - dum_md_yb))
        # round min_ext_w_od to fin grid.
        min_ext_w_od = -(-min_ext_w_od // fin_p)

        if min_ext_w_od <= max_ext_w_no_od + 1:
            # we can transition from no-dummy to dummy seamlessly
            return [min_ext_w]
        else:
            # there exists extension widths such that we need dummies but cannot draw it
            width_list = list(range(min_ext_w, max_ext_w_no_od + 1))
            width_list.append(min_ext_w_od)
            return width_list

    @classmethod
    def _get_ext_dummy_loc(cls, lch_unit, bot_od_idx, top_od_idx, bot_cpo_yt, top_cpo_yb, bot_md_yt, top_md_yb,
                           bot_imp_y, top_imp_y):
        """ calculate extension dummy location if we only draw one dummy. """
        cpo_od_sp = cls.tech_constants['cpo_od_sp']
        fin_p = cls.tech_constants['fin_pitch']
        fin_h = cls.tech_constants['fin_h']
        od_nfin_min = cls.tech_constants['od_nfin_min']
        md_od_exty = cls.tech_constants['md_od_exty']
        imp_od_ency = cls.tech_constants['imp_od_ency']
        od_sp_nfin_max = cls.tech_constants['od_sp_nfin_max']
        md_sp = cls.tech_constants['md_sp']
        md_h_min = cls.tech_constants['md_h_min']

        fin_p2 = fin_p // 2
        fin_h2 = fin_h // 2

        # calculate minimum OD coordinates
        md_yb_min = bot_md_yt + md_sp
        md_yt_max = top_md_yb - md_sp
        od_yb_min = max(bot_cpo_yt + cpo_od_sp, md_yb_min + md_od_exty, bot_imp_y + imp_od_ency)
        od_yt_max = min(top_cpo_yb - cpo_od_sp, md_yt_max - md_od_exty, top_imp_y - imp_od_ency)

        od_area = top_od_idx - bot_od_idx
        od_sp = min((od_area - od_nfin_min) // 2, od_sp_nfin_max)
        od_nfin = od_area - (od_sp * 2) + 1
        od_yb = (bot_od_idx + od_sp) * fin_p + fin_p2 - fin_h2
        od_yt = od_yb + (od_nfin - 1) * fin_p + fin_h

        # make sure OD Y coordinates are legal.
        od_h_min = (od_nfin_min - 1) * fin_p + fin_h
        if od_yb < od_yb_min:
            od_yb = -(-(od_yb_min - fin_p2 + fin_h2) // fin_p) * fin_p + fin_p2 - fin_h2
            od_yt = max(od_yb + od_h_min, od_yt)
        if od_yt > od_yt_max:
            od_yt = (od_yt_max - fin_p2 - fin_h2) // fin_p * fin_p + fin_p2 + fin_h2
            od_yb = min(od_yt - od_h_min, od_yb)

        # compute MD Y coordinates.
        md_h = max(md_h_min, od_yt - od_yb + 2 * md_od_exty)
        od_yc = (od_yb + od_yt) // 2
        md_yb = od_yc - md_h // 2
        md_yt = md_yb + md_h
        # make sure MD Y coordinates are legal
        if md_yb < md_yb_min:
            md_yb = md_yb_min
            md_yt = max(md_yt, md_yb + md_h_min)
        if md_yt > md_yt_max:
            md_yt = md_yt_max
            md_yb = min(md_yt - md_h_min, md_yb)

        return [(od_yb, od_yt)], [(md_yb, md_yt)]

    @classmethod
    def get_ext_info(cls, lch_unit, w, fg, top_ext_info, bot_ext_info):
        # type: (int, int, int, ExtInfo, ExtInfo) -> Dict[str, Any]
        """Draw extension block.

        extension block has zero or more rows of dummy transistors, the OD spacing
        is guarantee to be < 0.6um so when guard ring edge draw substrate contact
        in the same rows, we meet the guard ring OD separation constraint.  Most layout
        is straight-forward, but getting the implant right is very tricky.

        Extension implant strategy:

        constraints are:
        1. we cannot have checker-board pattern PP/NP.
        2. PP/NP minimum width needs to be met
        3. OD cannot intersect multiple types of implant.

        we use the following strategy (note that in LaygoBase, a transistor row can have
        both transistor or substrate):

        cases:
        1. top and bottom are same flavor transistor / sub (e.g. nch + nch or nch + ptap).
           split at middle, draw more dummy OD on substrate side.
        2. top and bottom are same flavor sub.
           split at middle.  The split point is chosen based on threshold alphabetical
           comparison, so we make sure we consistently favor one threshold over another.
        3. top and bottom are same flavor transistor.
            split at middle.  If there's OD, we force to use transistor implant.  This avoid constraint 3.
        4. top and bottom row are different flavor sub.
            split at middle, draw more dummy OD on ptap side.
        5. top and bottom are different flavor, transistor and sub.
            we use transistor implant
        6. top and bottom are different transistor.
            split, force to use transistor implant to avoid constraint 1.
        """
        md_od_exty = cls.tech_constants['md_od_exty']
        fin_h = cls.tech_constants['fin_h']
        fin_p = cls.tech_constants['fin_pitch']
        od_nfin_min = cls.tech_constants['od_nfin_min']
        od_nfin_max = cls.tech_constants['od_nfin_max']
        od_sp_nfin_max = cls.tech_constants['od_sp_nfin_max']
        cpo_spy = cls.tech_constants['cpo_spy']
        imp_od_ency = cls.tech_constants['imp_od_ency']
        md_h_min = cls.tech_constants['md_h_min']
        cpo_h = cls.tech_constants['cpo_h']

        mos_constants = cls.get_mos_tech_constants(lch_unit)
        m1_w = mos_constants['mos_conn_w']
        sd_pitch = mos_constants['sd_pitch']
        md_w = mos_constants['md_w']

        fin_p2 = fin_p // 2
        fin_h2 = fin_h // 2
        yt = w * fin_p
        yc = yt // 2

        lr_edge_info = EdgeInfo(od_type='dum')
        if w == 0:
            # just draw CPO
            layout_info = dict(
                lch_unit=lch_unit,
                md_w=md_w,
                fg=fg,
                sd_pitch=sd_pitch,
                array_box_xl=0,
                array_box_y=(0, 0),
                draw_od=True,
                row_info_list=[],
                lay_info_list=[(('CutPoly', 'drawing'), 0, -cpo_h // 2, cpo_h // 2)],
                adj_info_list=[],
                left_blk_info=None,
                right_blk_info=None,
                fill_info_list=[],

                # information needed for computing edge block layout
                blk_type='ext',
                imp_params=None,
            )

            return dict(
                layout_info=layout_info,
                left_edge_info=(lr_edge_info, []),
                right_edge_info=(lr_edge_info, []),
            )

        # step 1: compute OD Y coordinates
        bot_od_yt = -bot_ext_info.od_margin
        bot_od_yt_fin = (bot_od_yt - fin_p2 - fin_h2) // fin_p
        top_od_yb = yt + top_ext_info.od_margin
        top_od_yb_fin = (top_od_yb - fin_p2 + fin_h2) // fin_p
        area = top_od_yb_fin - bot_od_yt_fin
        od_fin_list = fill_symmetric_const_space(area, od_sp_nfin_max, od_nfin_min, od_nfin_max, offset=bot_od_yt_fin)

        # check if we draw one or two CPO.  Compute threshold split Y coordinates accordingly.
        cpo2_w = -(-(cpo_spy + cpo_h) // fin_p)  # type: int
        one_cpo = (w < cpo2_w)

        # calculate fill
        m1_sp_max = cls.tech_constants['m1_sp_max']
        m1_fill_lmin = cls.tech_constants['m1_fill_lmin']
        m1_fill_lmax = cls.tech_constants['m1_fill_lmax']
        area_yb = -bot_ext_info.m1_margin
        area_yt = yt + top_ext_info.m1_margin
        fill_y_list = fill_symmetric_const_space(area_yt - area_yb, m1_sp_max, m1_fill_lmin,
                                                 m1_fill_lmax, offset=area_yb)

        lay_info_list = []
        cpo_lay = ('CutPoly', 'drawing')
        if not od_fin_list:
            # no dummy OD
            od_x_list = []
            od_y_list = md_y_list = [(0, 0)]

            if one_cpo:
                po_y_list = [(0, 0)]
                imp_split_y = (yc, yc)
                # compute adjacent row geometry
                adj_edgel_infos = [bot_ext_info.edgel_info, top_ext_info.edgel_info]
                adj_edger_infos = [bot_ext_info.edger_info, top_ext_info.edger_info]
                adj_row_list = [AdjRowInfo(po_types=bot_ext_info.po_types,
                                           po_y=(0, yc),
                                           ),
                                AdjRowInfo(po_types=top_ext_info.po_types,
                                           po_y=(yc, yt),
                                           )]
                lay_info_list.append((cpo_lay, 0, yc - cpo_h // 2, yc + cpo_h // 2))
            else:
                po_y_list = [(0, yt)]
                imp_split_y = (0, yt)
                adj_row_list = []
                adj_edgel_infos = []
                adj_edger_infos = []
                lay_info_list.append((cpo_lay, 0, -cpo_h // 2, cpo_h // 2))
                lay_info_list.append((cpo_lay, 0, yt - cpo_h // 2, yt + cpo_h // 2))

        else:
            # has dummy OD, compute OD X/Y coordinates
            adj_row_list = []
            adj_edgel_infos = []
            adj_edger_infos = []
            od_x_list = (0, fg)
            # add OD and CPO layout information, also calculate fill
            num_dod = len(od_fin_list)
            if num_dod == 1:
                # if we only have 1 dummy, use manual algorithm to make sure we satisfy MD-MD and CPO-MD rules
                bot_cpo_yt = cpo_h // 2
                top_cpo_yb = yt - cpo_h // 2
                bot_md_yt = -bot_ext_info.md_margin
                top_md_yb = yt + top_ext_info.md_margin
                bot_imp_y = bot_ext_info.imp_min_w
                top_imp_y = yt - top_ext_info.imp_min_w
                od_y_list, md_y_list = cls._get_ext_dummy_loc(lch_unit, bot_od_yt_fin, top_od_yb_fin,
                                                              bot_cpo_yt, top_cpo_yb, bot_md_yt, top_md_yb,
                                                              bot_imp_y, top_imp_y)
            else:
                # for 2 for more dummy, od_sp_nfin_max (12) and od_nfin_max (20) values guarantee that
                # all dummy locations are DRC clean
                od_y_list = []
                md_y_list = []
                for a, b in od_fin_list:
                    od_yb = fin_p2 - fin_h2 + a * fin_p
                    od_yt = fin_p2 + fin_h2 + b * fin_p
                    od_yc = (od_yb + od_yt) // 2
                    md_h = max(md_h_min, od_yt - od_yb + 2 * md_od_exty)
                    md_yb = od_yc - md_h // 2
                    md_yt = od_yc + md_h // 2
                    od_y_list.append((od_yb, od_yt))
                    md_y_list.append((md_yb, md_yt))

            # get PO/CPO locations
            cpo_yc = 0
            cpo_yc_list = []
            po_y_list = []
            for idx, (od_yb, od_yt) in enumerate(od_y_list):
                # find next CPO coordinates
                if idx + 1 < num_dod:
                    next_cpo_yc = (od_yt + od_y_list[idx + 1][0]) // 2
                else:
                    next_cpo_yc = yt

                # record PO Y coordinates
                po_y_list.append((cpo_yc, next_cpo_yc))

                # add CPO
                lay_info_list.append((cpo_lay, 0, cpo_yc - cpo_h // 2, cpo_yc + cpo_h // 2))
                cpo_yc_list.append(cpo_yc)
                # update CPO coordinates.
                cpo_yc = next_cpo_yc

            # add last CPO
            lay_info_list.append((cpo_lay, 0, yt - cpo_h // 2, yt + cpo_h // 2))
            cpo_yc_list.append(yt)

            # compute implant split Y coordinates
            if num_dod % 2 == 0:
                # we can split exactly in middle
                imp_split_y = (yc, yc)
            else:
                # Find the two middle CPO coordinates.
                top_cpo_idx = num_dod // 2
                od_yb, od_yt = od_y_list[top_cpo_idx]
                imp_split_y = (od_yb - imp_od_ency, od_yt + imp_od_ency)

        # compute implant and threshold layer information
        top_mtype, top_row_type = top_ext_info.mtype
        top_thres = top_ext_info.thres
        bot_mtype, bot_row_type = bot_ext_info.mtype
        bot_thres = bot_ext_info.thres
        bot_imp = 'nch' if (bot_row_type == 'nch' or bot_row_type == 'ptap') else 'pch'
        top_imp = 'nch' if (top_row_type == 'nch' or top_row_type == 'ptap') else 'pch'
        bot_tran = (bot_row_type == 'nch' or bot_row_type == 'pch')
        top_tran = (top_row_type == 'nch' or top_row_type == 'pch')
        # figure out where to separate top/bottom implant/threshold.
        if bot_imp == top_imp:
            if bot_tran != top_tran:
                # case 1
                sep_idx = 0 if bot_tran else 1
            elif bot_tran:
                # case 3
                sep_idx = 0 if bot_thres <= top_thres else 1
                if od_x_list:
                    bot_mtype = top_mtype = bot_imp
            else:
                # case 2
                sep_idx = 0 if bot_thres <= top_thres else 1
        else:
            if bot_tran != top_tran:
                # case 5
                if bot_tran:
                    top_mtype = bot_imp
                    top_thres = bot_thres
                    sep_idx = 1
                else:
                    bot_mtype = top_imp
                    bot_thres = top_thres
                    sep_idx = 0
            elif bot_tran:
                # case 6
                bot_mtype = bot_imp
                top_mtype = top_imp
                sep_idx = 1 if bot_imp == 'nch' else 0
            else:
                # case 4
                sep_idx = 1 if bot_imp == 'nch' else 0

        # add implant layers
        imp_ysep = imp_split_y[sep_idx]
        imp_params = [(bot_mtype, bot_thres, 0, imp_ysep, 0, imp_ysep),
                      (top_mtype, top_thres, imp_ysep, yt, imp_ysep, yt)]

        for mtype, thres, imp_yb, imp_yt, thres_yb, thres_yt in imp_params:
            for lay in cls.get_mos_layers(mtype, thres):
                if lay[0].startswith('VT'):
                    cur_yb, cur_yt = thres_yb, thres_yt
                else:
                    cur_yb, cur_yt = imp_yb, imp_yt
                lay_info_list.append((lay, 0, cur_yb, cur_yt))

        # construct row_info_list, now we know where the implant splits
        row_info_list = []
        for od_y, po_y, md_y in zip(od_y_list, po_y_list, md_y_list):
            cur_mtype = bot_mtype if max(od_y[0], od_y[1]) < imp_ysep else top_mtype
            cur_sub_type = 'ptap' if cur_mtype == 'nch' or cur_mtype == 'ptap' else 'ntap'
            row_info_list.append(RowInfo(od_x_list=od_x_list, od_y=od_y, od_type=('dum', cur_sub_type),
                                         po_y=po_y, md_y=md_y))

        # compute metal 1 fill locations
        fill_x_list = [(idx * sd_pitch - m1_w // 2, idx * sd_pitch + m1_w // 2)
                       for idx in range(0, fg + 1)]
        fill_info = FillInfo(layer=('M1', 'drawing'), exc_layer=None,
                             x_intv_list=fill_x_list, y_intv_list=fill_y_list)
        # create layout information dictionary
        layout_info = dict(
            lch_unit=lch_unit,
            md_w=md_w,
            fg=fg,
            sd_pitch=sd_pitch,
            array_box_xl=0,
            array_box_y=(0, yt),
            draw_od=True,
            row_info_list=row_info_list,
            lay_info_list=lay_info_list,
            adj_info_list=adj_row_list,
            left_blk_info=None,
            right_blk_info=None,
            fill_info_list=[fill_info],

            # information needed for computing edge block layout
            blk_type='ext',
            imp_params=imp_params,
        )

        return dict(
            layout_info=layout_info,
            left_edge_info=(lr_edge_info, adj_edgel_infos),
            right_edge_info=(lr_edge_info, adj_edger_infos),
        )

    @classmethod
    def _get_sub_m1_y(cls, lch_unit, od_yc, od_nfin):
        """Get M1 Y coordinates for substrate connection."""
        via_info = cls.get_ds_via_info(lch_unit, od_nfin)
        m1_h = via_info['m1_h']

        m1_yb = od_yc - m1_h // 2
        m1_yt = od_yc + m1_h // 2

        return m1_yb, m1_yt

    @classmethod
    def get_substrate_info(cls, lch_unit, w, sub_type, threshold, fg, blk_pitch=1, **kwargs):
        # type: (int, int, str, str, int, int, **kwargs) -> Dict[str, Any]
        """Get substrate layout information.

        Layout is quite simple.  We use M0PO to short adjacent S/D together, so dummies can be
        connected using only M2 or below.

        Strategy:

        1. Find bottom M0_PO and bottom OD coordinates from spacing rules.
        #. Find template top coordinate by enforcing symmetry around OD center.
        #. Round up template height to blk_pitch, then recenter OD.
        #. make sure MD/M1 are centered on OD.
        """

        md_od_ext = cls.tech_constants['md_od_ext']
        fin_h = cls.tech_constants['fin_h']
        fin_p = cls.tech_constants['fin_pitch']
        mp_h = cls.tech_constants['mp_h']
        mp_cpo_sp = cls.tech_constants['mp_cpo_sp']
        mp_md_sp = cls.tech_constants['mp_md_sp']
        mp_spy = cls.tech_constants['mp_spy']
        cpo_h = cls.tech_constants['cpo_h']
        md_h_min = cls.tech_constants['md_h_min']
        md_w = cls.tech_constants['md_w']

        fin_p2 = fin_p // 2
        fin_h2 = fin_h // 2

        mos_constants = cls.get_mos_tech_constants(lch_unit)
        sd_pitch = mos_constants['sd_pitch']

        # figure out od/md height
        od_h = (w - 1) * fin_p + fin_h
        md_h = max(md_h_min, od_h + 2 * md_od_ext)
        md_od_ext = (md_h - od_h) // 2

        # step 1: figure out Y coordinate of bottom CPO
        cpo_bot_yt = cpo_h // 2

        # step 2: find bottom M0_PO coordinate
        mp_yb = max(mp_spy // 2, cpo_bot_yt + mp_cpo_sp)
        mp_yt = mp_yb + mp_h

        # step 3: find OD coordinate
        od_bfin_yc = mp_yt + mp_md_sp + md_od_ext
        od_bfin_yc = -(-(od_bfin_yc - fin_p2) // fin_p) * fin_p + fin_p2
        od_yb = od_bfin_yc - fin_h2
        od_yt = od_yb + od_h
        cpo_top_yc = od_yt + od_yb
        # fix substrate height quantization, then recenter OD location
        blk_pitch = lcm([blk_pitch, fin_p])
        blk_h = -(-cpo_top_yc // blk_pitch) * blk_pitch
        cpo_top_yc = blk_h
        od_yb = blk_h // 2 - od_h // 2
        od_yb = (od_yb - fin_p2 + fin_h2) // fin_p * fin_p + fin_p2 - fin_h2
        od_yt = od_yb + od_h
        od_yc = (od_yb + od_yt) // 2

        # step 3: find MD Y coordinates
        md_yb = (od_yb + od_yt - md_h) // 2
        md_yt = md_yb + md_h

        # step 3.5: update MP Y coordinates, compute M1 upper and lower bound
        # bottom MP
        via_info = cls.get_ds_via_info(lch_unit, w)
        gv0_h = via_info['h'][0]
        top_ency = via_info['top_ency'][0]
        gm1_delta = gv0_h // 2 + top_ency
        mp_yt = md_yb - mp_md_sp
        mp_yb = mp_yt - mp_h
        mp_yc = (mp_yt + mp_yb) // 2
        g_m1_yb = mp_yc - gm1_delta
        # top MP
        mp_yb = md_yt + mp_md_sp
        mp_yt = mp_yb + mp_h
        mp_yc = (mp_yb + mp_yt) // 2
        g_m1_yt = mp_yc + gm1_delta

        # step 4: compute PO locations
        po_yb, po_yt = 0, cpo_top_yc

        # step 5: compute layout information
        lay_info_list = [(lay, 0, po_yb, po_yt) for lay in cls.get_mos_layers(sub_type, threshold)]
        lr_edge_info = EdgeInfo(od_type='sub')

        ds_conn_y = (g_m1_yb, g_m1_yt)
        fill_info = FillInfo(layer=('M1', 'drawing'), exc_layer=None,
                             x_intv_list=[], y_intv_list=[ds_conn_y])

        layout_info = dict(
            # information needed for draw_mos
            lch_unit=lch_unit,
            md_w=md_w,
            fg=fg,
            sd_pitch=sd_pitch,
            array_box_xl=0,
            array_box_y=(po_yb, po_yt),
            draw_od=True,
            row_info_list=[RowInfo(od_x_list=[(0, fg)],
                                   od_y=(od_yb, od_yt),
                                   od_type=('sub', sub_type),
                                   po_y=(po_yb, po_yt),
                                   md_y=(md_yb, md_yt)), ],
            lay_info_list=lay_info_list,
            adj_info_list=[],
            left_blk_info=None,
            right_blk_info=None,
            fill_info_list=[fill_info],

            # information needed for computing edge block layout
            blk_type='sub',
            imp_params=None,
        )

        mtype = (sub_type, sub_type)
        po_types = (1,) * fg
        ext_top_info = ExtInfo(
            mx_margin=po_yt - g_m1_yt,
            od_margin=po_yt - od_yt,
            md_margin=po_yt - md_yt,
            m1_margin=po_yt - g_m1_yt,
            imp_min_w=0,
            mtype=mtype,
            thres=threshold,
            po_types=po_types,
            edgel_info=lr_edge_info,
            edger_info=lr_edge_info,
        )
        ext_bot_info = ExtInfo(
            mx_margin=g_m1_yb - po_yb,
            od_margin=od_yb - po_yb,
            md_margin=md_yb - po_yb,
            m1_margin=g_m1_yb - po_yb,
            imp_min_w=0,
            mtype=mtype,
            thres=threshold,
            po_types=po_types,
            edgel_info=lr_edge_info,
            edger_info=lr_edge_info,
        )

        return dict(
            layout_info=layout_info,
            sd_yc=od_yc,
            ext_top_info=ext_top_info,
            ext_bot_info=ext_bot_info,
            left_edge_info=(lr_edge_info, []),
            right_edge_info=(lr_edge_info, []),
            blk_height=po_yt,
            gb_conn_y=ds_conn_y,
            ds_conn_y=ds_conn_y,
        )

    @classmethod
    def get_analog_end_info(cls, lch_unit, sub_type, threshold, fg, is_end, blk_pitch):
        # type: (int, str, str, int, bool, int) -> Dict[str, Any]
        """Get substrate end layout information

        Layout is quite simple.  We draw the right CPO width, and extend PO so PO-CPO overlap
        rule is satisfied.

        Strategy:
        If is not end (array abutment), just draw CPO.  If is end:
        1. find margin between bottom coordinate and array box bottom, round up to block pitch.
        #. Compute CPO location, and PO coordinates if we need to draw PO.
        #. Compute implant location.
        """
        fin_h = cls.tech_constants['fin_h']
        fin_p = cls.tech_constants['fin_pitch']
        cpo_po_ency = cls.tech_constants['cpo_po_ency']
        md_w = cls.tech_constants['md_w']
        cpo_h_mid = cls.tech_constants['cpo_h']

        fin_p2 = fin_p // 2
        fin_h2 = fin_h // 2

        mos_constants = cls.get_mos_tech_constants(lch_unit)
        sd_pitch = mos_constants['sd_pitch']

        lr_edge_info = EdgeInfo(od_type='sub')
        if is_end:
            cpo_h = cls.tech_constants['cpo_h_end']

            # step 1: figure out Y coordinates of CPO
            blk_pitch = lcm([blk_pitch, fin_p])
            # first assume top Y coordinate is 0
            arr_yt = 0
            cpo_bot_yt = arr_yt + cpo_h_mid // 2
            cpo_bot_yb = cpo_bot_yt - cpo_h
            finbound_yb = arr_yt - fin_p2 - fin_h2
            min_yb = min(finbound_yb, cpo_bot_yb)
            # make sure all layers are in first quadrant
            if min_yb < 0:
                yshift = -(min_yb // blk_pitch) * blk_pitch
                arr_yt += yshift
                cpo_bot_yt += yshift
                cpo_bot_yb += yshift
                finbound_yb += yshift

            finbound_yt = arr_yt + fin_p2 + fin_h2
            cpo_bot_yc = (cpo_bot_yb + cpo_bot_yt) // 2
            po_yt = arr_yt
            po_yb = cpo_bot_yt - cpo_po_ency
            if po_yt > po_yb:
                adj_info_list = [AdjRowInfo(po_y=(po_yb, po_yt), po_types=(1,) * fg)]
                adj_edge_infos = [lr_edge_info]
            else:
                adj_info_list = []
                adj_edge_infos = []

            lay_info_list = [(('CutPoly', 'drawing'), 0, cpo_bot_yb, cpo_bot_yt)]
            for lay in cls.get_mos_layers(sub_type, threshold):
                if lay[0] == 'FinArea':
                    yb, yt = finbound_yb, finbound_yt
                else:
                    yb, yt = min(po_yb, cpo_bot_yc), arr_yt
                if yt > yb:
                    lay_info_list.append((lay, 0, yb, yt))
        else:
            # we just draw CPO
            arr_yt = 0
            cpo_h = mos_constants['cpo_h']
            lay_info_list = [(('CutPoly', 'drawing'), 0, -cpo_h // 2, cpo_h // 2)]
            adj_info_list = []
            adj_edge_infos = []

        layout_info = dict(
            # information needed for draw_mos
            lch_unit=lch_unit,
            md_w=md_w,
            fg=fg,
            sd_pitch=sd_pitch,
            array_box_xl=0,
            array_box_y=(0, arr_yt),
            draw_od=True,
            row_info_list=[],
            lay_info_list=lay_info_list,
            adj_info_list=adj_info_list,
            left_blk_info=None,
            right_blk_info=None,
            fill_info_list=[],

            # information needed for computing edge block layout
            blk_type='end',
            imp_params=None,
            left_edge_info=(lr_edge_info, adj_edge_infos),
            right_edge_info=(lr_edge_info, adj_edge_infos),
        )

        return dict(
            layout_info=layout_info,
            left_edge_info=(lr_edge_info, adj_edge_infos),
            right_edge_info=(lr_edge_info, adj_edge_infos),
        )

    @classmethod
    def get_outer_edge_info(cls, grid, guard_ring_nf, layout_info, top_layer, is_end, adj_blk_info):
        # type: (RoutingGrid, int, Dict[str, Any], int, bool, Optional[Any]) -> Dict[str, Any]
        lch_unit = layout_info['lch_unit']
        edge_info = cls.get_edge_info(grid, lch_unit, guard_ring_nf, top_layer, is_end)
        edge_xl = edge_info['dx_edge']
        cpo_xl = min(edge_xl, edge_info['cpo_xl'])
        # compute new row_info_list
        # noinspection PyProtectedMember
        row_info_list = [rinfo._replace(od_x_list=[]) for rinfo in layout_info['row_info_list']]

        # compute new lay_info_list
        lay_info_list = layout_info['lay_info_list']
        imp_params = layout_info['imp_params']
        if guard_ring_nf == 0 or imp_params is None:
            # we keep all implant layers, just update left coordinate.
            new_lay_list = [(lay, cpo_xl if lay[0] == 'CutPoly' else edge_xl, yb, yt)
                            for lay, _, yb, yt in lay_info_list]
        else:
            # we need to convert implant layers to substrate implants
            # first, get all CPO layers
            new_lay_list = [(lay, cpo_xl, yb, yt) for lay, _, yb, yt in lay_info_list if lay[0] == 'CutPoly']
            # compute substrate implant layers
            for mtype, thres, imp_yb, imp_yt, thres_yb, thres_yt in imp_params:
                sub_type = 'ptap' if mtype == 'nch' or mtype == 'ptap' else 'ntap'
                for lay in cls.get_mos_layers(sub_type, thres):
                    cur_yb, cur_yt = imp_yb, imp_yt
                    new_lay_list.append((lay, edge_xl, cur_yb, cur_yt))

        # compute new adj_info_list
        adj_info_list = layout_info['adj_info_list']
        if adj_blk_info is None:
            adj_blk_info = (None, [None] * len(adj_info_list))

        new_adj_list = []
        fg = edge_info['outer_fg']
        if fg > 0:
            for adj_edge_info, adj_info in zip(adj_blk_info[1], adj_info_list):
                if adj_edge_info is not None and (adj_edge_info.od_type == 'mos' or adj_edge_info.od_type == 'sub'):
                    po_types = (0,) * (fg - 1) + (1,)
                else:
                    po_types = (0,) * fg
                # noinspection PyProtectedMember
                new_adj_list.append(adj_info._replace(po_types=po_types))

        # compute new fill information
        sd_pitch = layout_info['sd_pitch']
        if fg > 0:
            mos_constants = cls.get_mos_tech_constants(lch_unit)
            m1_w = mos_constants['mos_conn_w']
            x_intv_list = [(edge_xl + sd_pitch - m1_w // 2, edge_xl + sd_pitch + m1_w // 2)]
        else:
            x_intv_list = []
        # noinspection PyProtectedMember
        fill_info_list = [f._replace(x_intv_list=x_intv_list) for f in layout_info['fill_info_list']]

        return dict(
            lch_unit=lch_unit,
            md_w=layout_info['md_w'],
            fg=fg,
            sd_pitch=sd_pitch,
            array_box_xl=edge_xl,
            array_box_y=layout_info['array_box_y'],
            draw_od=True,
            row_info_list=row_info_list,
            lay_info_list=new_lay_list,
            adj_info_list=new_adj_list,
            left_blk_info=EdgeInfo(od_type=None),
            right_blk_info=adj_blk_info[0],
            fill_info_list=fill_info_list,

            blk_type='edge' if guard_ring_nf == 0 else 'gr_edge',
        )

    @classmethod
    def get_gr_sub_info(cls, guard_ring_nf, layout_info):
        # type: (int, Dict[str, Any]) -> Dict[str, Any]

        lch_unit = layout_info['lch_unit']
        edge_constants = cls.get_edge_tech_constants(lch_unit)
        gr_nf_min = edge_constants['gr_nf_min']
        gr_sub_fg_margin = edge_constants['gr_sub_fg_margin']

        if guard_ring_nf < gr_nf_min:
            raise ValueError('guard_ring_nf = %d < %d' % (guard_ring_nf, gr_nf_min))

        fg = gr_nf_min + 2 + 2 * gr_sub_fg_margin

        # compute new row_info_list
        od_x_list = [(gr_sub_fg_margin + 1, gr_sub_fg_margin + 1 + gr_nf_min)]
        # noinspection PyProtectedMember
        row_info_list = [rinfo._replace(od_x_list=od_x_list, od_type=('sub', rinfo.od_type[1]))
                         for rinfo in layout_info['row_info_list']]

        # compute new lay_info_list
        lay_info_list = layout_info['lay_info_list']
        imp_params = layout_info['imp_params']
        if imp_params is None:
            # don't have to recompute implant layers
            new_lay_list = lay_info_list
        else:
            # we need to convert implant layers to substrate implants
            # first, get all CPO layers
            new_lay_list = [lay_info for lay_info in lay_info_list if lay_info[0][0] == 'CutPoly']
            # compute substrate implant layers
            for mtype, thres, imp_yb, imp_yt, thres_yb, thres_yt in imp_params:
                sub_type = 'ptap' if mtype == 'nch' or mtype == 'ptap' else 'ntap'
                for lay in cls.get_mos_layers(sub_type, thres):
                    cur_yb, cur_yt = imp_yb, imp_yt
                    new_lay_list.append((lay, 0, cur_yb, cur_yt))

        # compute new adj_info_list
        po_types = (0,) * gr_sub_fg_margin + (1,) * (gr_nf_min + 2) + (0,) * gr_sub_fg_margin
        # noinspection PyProtectedMember
        adj_info_list = [ar_info._replace(po_types=po_types) for ar_info in layout_info['adj_info_list']]

        # compute new fill information
        # noinspection PyProtectedMember
        fill_info_list = [f._replace(x_intv_list=[]) for f in layout_info['fill_info_list']]

        return dict(
            lch_unit=lch_unit,
            md_w=layout_info['md_w'],
            fg=fg,
            sd_pitch=layout_info['sd_pitch'],
            array_box_xl=0,
            array_box_y=layout_info['array_box_y'],
            draw_od=True,
            row_info_list=row_info_list,
            lay_info_list=new_lay_list,
            adj_info_list=adj_info_list,
            left_blk_info=None,
            right_blk_info=None,
            fill_info_list=fill_info_list,

            blk_type='gr_sub',
        )

    @classmethod
    def get_gr_sep_info(cls, layout_info, adj_blk_info):
        # type: (Dict[str, Any], Any) -> Dict[str, Any]

        lch_unit = layout_info['lch_unit']
        edge_constants = cls.get_edge_tech_constants(lch_unit)
        fg = edge_constants['gr_sep_fg']

        # compute new row_info_list
        # noinspection PyProtectedMember
        row_info_list = [rinfo._replace(od_x_list=[]) for rinfo in layout_info['row_info_list']]

        # compute new adj_info_list
        adj_info_list = layout_info['adj_info_list']
        new_adj_list = []
        for adj_edge_info, adj_info in zip(adj_blk_info[1], adj_info_list):
            if adj_edge_info.od_type == 'mos' or adj_edge_info.od_type == 'sub':
                po_types = (0,) * (fg - 1) + (1,)
            else:
                po_types = (0,) * fg
            # noinspection PyProtectedMember
            new_adj_list.append(adj_info._replace(po_types=po_types))

        # compute new fill information
        mos_constants = cls.get_mos_tech_constants(lch_unit)
        m1_w = mos_constants['mos_conn_w']
        x_intv_list = [(-m1_w // 2, m1_w // 2)]
        # noinspection PyProtectedMember
        fill_info_list = [f._replace(x_intv_list=x_intv_list) for f in layout_info['fill_info_list']]

        return dict(
            lch_unit=lch_unit,
            md_w=layout_info['md_w'],
            fg=fg,
            sd_pitch=layout_info['sd_pitch'],
            array_box_xl=0,
            array_box_y=layout_info['array_box_y'],
            draw_od=True,
            row_info_list=row_info_list,
            lay_info_list=layout_info['lay_info_list'],
            adj_info_list=new_adj_list,
            left_blk_info=None,
            right_blk_info=adj_blk_info[0],
            fill_info_list=fill_info_list,

            blk_type='gr_sep',
        )

    @classmethod
    def draw_mos(cls, template, layout_info):
        # type: (TemplateBase, Dict[str, Any]) -> None
        """Draw transistor related layout.

        the layout information dictionary should contain the following entries:


        blk_type
            a string describing the type of this block.
        lch_unit
            channel length in resolution units
        md_w
            M0OD width in resolution units
        fg
            the width of this template in number of fingers
        sd_pitch
            the source/drain pitch of this template.
        array_box_xl
            array box left coordinate.  All PO X coordinates are calculated
            relative to this point.
        array_box_y
            array box Y coordinates as two-element integer tuple.
        od_type
            the OD type in this template.  Either 'mos', 'sub', or 'dum'.
        draw_od
            If False, we will not draw OD in this template.  This is used for
            supporting the ds_dummy option.
        row_info_list
            a list of named tuples for each transistor row we need to draw in
            this template.

            a transistor row is defines as a row of OD/PO/MD that either acts
            as an active device or used for dummy fill purposes.  Each named tuple
            should have the following entries:

            od_x_list
                A list of transistor X intervals in finger index.
            od_y
                OD Y coordinates as two-element integer tuple.
            po_y
                PO Y coordinates as two-element integer tuple.
            md_y
                MD Y coordinates as two-element integer tuple.
        lay_info_list
            a list of layers to draw.  Each layer information is a tuple
            of (imp_layer, xl, yb, yt).
        adj_info_list
            a list of named tuples for geometries belonging to adjacent
            rows.  Each named tuple should contain:

            po_y
                PO Y coordinates as two-element integer tuple.
            po_types
                list of po types.  1 for drawing, 0 for dummy.
        left_blk_info
            a tuple of (EdgeInfo, List[EdgeInfo]) that represents edge information
            of the left adjacent block.  These influences the geometry abutting the
            left block.  If None, assume default behavior.
        right_blk_info
            same as left_blk_info, but for the right edge.
        fill_info_list:
            a list of fill information named tuple.  Each tuple contains:

            layer
                the fill layer
            exc_layer
                the fill exclusion layer
            x_intv_list
                a list of X intervals of the fill
            y_intv_list
                a list of Y intervals of the fill

        Parameters
        ----------
        template : TemplateBase
            the template to draw the layout in.
        layout_info : Dict[str, Any]
            the layout information dictionary.
        """
        res = template.grid.resolution

        fin_pitch = cls.tech_constants['fin_pitch']
        fin_h = cls.tech_constants['fin_h']

        fin_pitch2 = fin_pitch // 2
        fin_h2 = fin_h // 2

        blk_type = layout_info['blk_type']
        lch_unit = layout_info['lch_unit']
        md_w = layout_info['md_w']
        fg = layout_info['fg']
        sd_pitch = layout_info['sd_pitch']
        arr_xl = layout_info['array_box_xl']
        arr_yb, arr_yt = layout_info['array_box_y']
        draw_od = layout_info['draw_od']
        row_info_list = layout_info['row_info_list']
        lay_info_list = layout_info['lay_info_list']
        adj_info_list = layout_info['adj_info_list']
        left_blk_info = layout_info['left_blk_info']
        right_blk_info = layout_info['right_blk_info']
        fill_info_list = layout_info['fill_info_list']

        default_edge_info = EdgeInfo(od_type=None)
        if left_blk_info is None:
            if fg == 1 and right_blk_info is not None:
                # make sure if we only have one finger, PO purpose is still chosen correctly.
                left_blk_info = right_blk_info
            else:
                left_blk_info = default_edge_info
        if right_blk_info is None:
            if fg == 1:
                # make sure if we only have one finger, PO purpose is still chosen correctly.
                right_blk_info = left_blk_info
            else:
                right_blk_info = default_edge_info

        blk_w = fg * sd_pitch + arr_xl

        # figure out transistor layout settings
        od_dum_lay = ('Active', 'dummy')
        po_dum_lay = ('Poly', 'dummy')
        md_lay = ('LiAct', 'drawing')

        po_xc = arr_xl + sd_pitch // 2
        # draw transistor rows
        for row_info in row_info_list:
            od_type = row_info.od_type[0]
            if od_type == 'dum' or od_type is None:
                od_lay = od_dum_lay
            else:
                od_lay = ('Active', 'drawing')
            od_x_list = row_info.od_x_list
            od_yb, od_yt = row_info.od_y
            po_yb, po_yt = row_info.po_y
            md_yb, md_yt = row_info.md_y

            po_on_od = [False] * fg
            md_on_od = [False] * (fg + 1)
            if od_yt > od_yb:
                # draw OD and figure out PO/MD info
                for od_start, od_stop in od_x_list:
                    # mark PO/MD indices that are on OD
                    if od_start - 1 >= 0:
                        po_on_od[od_start - 1] = True
                    for idx in range(od_start, od_stop + 1):
                        md_on_od[idx] = True
                        if idx < fg:
                            po_on_od[idx] = True

                    if draw_od:
                        od_xl = po_xc - lch_unit // 2 + (od_start - 1) * sd_pitch
                        od_xr = po_xc + lch_unit // 2 + od_stop * sd_pitch
                        template.add_rect(od_lay, BBox(od_xl, od_yb, od_xr, od_yt, res, unit_mode=True))

            # draw PO
            if po_yt > po_yb:
                for idx in range(fg):
                    po_xl = po_xc + idx * sd_pitch - lch_unit // 2
                    po_xr = po_xl + lch_unit
                    if po_on_od[idx]:
                        cur_od_type = od_type
                    else:
                        if idx == 0:
                            cur_od_type = left_blk_info.od_type
                        elif idx == fg - 1:
                            cur_od_type = right_blk_info.od_type
                        else:
                            cur_od_type = None

                    lay = ('Poly', 'drawing') if (cur_od_type == 'mos' or cur_od_type == 'sub') else po_dum_lay
                    template.add_rect(lay, BBox(po_xl, po_yb, po_xr, po_yt, res, unit_mode=True))

            # draw MD if it's physical
            if md_yt > md_yb and fg > 0:
                md_range = range(1, fg) if blk_type == 'gr_sub' else range(fg + 1)
                for idx in md_range:
                    if ((0 < idx < fg) or (idx == 0 and left_blk_info.draw_md) or
                            (idx == fg and right_blk_info.draw_md)):
                        md_xl = arr_xl + idx * sd_pitch - md_w // 2
                        md_xr = md_xl + md_w
                        if md_on_od[idx]:
                            template.add_rect(md_lay, BBox(md_xl, md_yb, md_xr, md_yt, res, unit_mode=True))

        # draw other layers
        for imp_lay, xl, yb, yt in lay_info_list:
            if imp_lay[0] == 'FinArea':
                # round to fin grid
                yb = (yb - fin_pitch2 + fin_h2) // fin_pitch * fin_pitch + fin_pitch2 - fin_h2
                yt = -(-(yt - fin_pitch2 - fin_h2) // fin_pitch) * fin_pitch + fin_pitch2 + fin_h2
            box = BBox(xl, yb, blk_w, yt, res, unit_mode=True)
            if box.is_physical():
                template.add_rect(imp_lay, box)

        # draw adjacent row geometries
        for adj_info in adj_info_list:
            po_yb, po_yt = adj_info.po_y
            for idx, po_type in enumerate(adj_info.po_types):
                lay = po_dum_lay if po_type == 0 else ('Poly', 'drawing')
                po_xl = po_xc + idx * sd_pitch - lch_unit // 2
                po_xr = po_xl + lch_unit
                template.add_rect(lay, BBox(po_xl, po_yb, po_xr, po_yt, res, unit_mode=True))

        # set size and add PR boundary
        arr_box = BBox(arr_xl, arr_yb, blk_w, arr_yt, res, unit_mode=True)
        bound_box = arr_box.extend(x=0, y=0, unit_mode=True)
        template.array_box = arr_box
        template.prim_bound_box = bound_box
        if bound_box.is_physical():
            template.add_cell_boundary(bound_box)

            # draw metal fill.  This only needs to be done if the template has nonzero area.
            for fill_info in fill_info_list:
                exc_lay = fill_info.exc_layer
                lay = fill_info.layer
                x_intv_list = fill_info.x_intv_list
                y_intv_list = fill_info.y_intv_list
                template.add_rect(exc_lay, bound_box)
                for xl, xr in x_intv_list:
                    for yb, yt in y_intv_list:
                        template.add_rect(lay, BBox(xl, yb, xr, yt, res, unit_mode=True))

    @classmethod
    def draw_substrate_connection(cls, template, layout_info, port_tracks, dum_tracks, dummy_only,
                                  is_laygo, is_guardring):
        # type: (TemplateBase, Dict[str, Any], List[int], List[int], bool, bool, bool) -> bool

        fin_h = cls.tech_constants['fin_h']
        fin_p = cls.tech_constants['fin_pitch']
        mp_md_sp = cls.tech_constants['mp_md_sp']
        mp_h = cls.tech_constants['mp_h']
        mp_po_ovl = cls.tech_constants['mp_po_ovl']

        lch_unit = layout_info['lch_unit']
        sd_pitch = layout_info['sd_pitch']
        row_info_list = layout_info['row_info_list']

        sd_pitch2 = sd_pitch // 2

        has_od = False
        for row_info in row_info_list:
            od_yb, od_yt = row_info.od_y
            if od_yt > od_yb:
                has_od = True
                # find current port name
                od_start, od_stop = row_info.od_x_list[0]
                fg = od_stop - od_start
                xshift = od_start * sd_pitch
                sub_type = row_info.od_type[1]
                port_name = 'VDD' if sub_type == 'ntap' else 'VSS'

                # draw substrate connection only if OD exists.
                od_yc = (od_yb + od_yt) // 2
                w = (od_yt - od_yb - fin_h) // fin_p + 1

                via_info = cls.get_ds_via_info(lch_unit, w, compact=is_guardring)

                # find X locations of M2/M3.
                if dummy_only:
                    # find X locations to draw vias
                    m1_x_list = [sd_pitch2 * int(2 * v + 1) for v in dum_tracks]
                    m3_x_list = []
                else:
                    # first, figure out port/dummy tracks
                    # since dummy tracks are on M2, to lower parasitics, we try to draw only as many dummy tracks
                    # as necessary. Also, every port track is also a dummy track (because to get to M3 we must
                    # get to M2).  With these constraints, our track selection algorithm is as follows:
                    # 1. for every dummy track, if its not adjacent to any port tracks, add it to port tracks (this
                    #    improves dummy connection resistance to supply).
                    # 2. Try to add as many unused tracks to port tracks as possible, while making sure we don't end
                    #    up with adjacent port tracks.  This improves substrate connection resistance to supply.
                    # 3. now, M2 tracks is the union of dummy tracks and port tracks, M3 tracks is port tracks.

                    # use half track indices so we won't have rounding errors.
                    phtr_set = set((int(2 * v + 1) for v in port_tracks))
                    dhtr_set = set((int(2 * v + 1) for v in dum_tracks))
                    # add as many dummy tracks as possible to port tracks
                    for d in dhtr_set:
                        if d + 2 not in phtr_set and d - 2 not in phtr_set:
                            phtr_set.add(d)
                    # add as many unused tracks as possible to port tracks
                    for htr in range(0, 2 * fg + 1, 2):
                        if htr + 2 not in phtr_set and htr - 2 not in phtr_set:
                            phtr_set.add(htr)
                    # add all port sets to dummy set
                    dhtr_set.update(phtr_set)
                    # find X coordinates
                    m1_x_list = [sd_pitch2 * v for v in sorted(dhtr_set)]
                    m3_x_list = [sd_pitch2 * v for v in sorted(phtr_set)]

                m1_warrs, m3_warrs = cls._draw_ds_via(template, sd_pitch, od_yc, fg, via_info, True, 1, 1,
                                                      m1_x_list, m3_x_list, xshift=xshift)
                template.add_pin(port_name, m1_warrs, show=False)
                template.add_pin(port_name, m3_warrs, show=False)

                if not is_guardring:
                    md_yb, md_yt = row_info.md_y
                    # draw M0PO connections
                    res = template.grid.resolution
                    gv0_h = via_info['h'][0]
                    gv0_w = via_info['w'][0]
                    top_encx = via_info['top_encx'][0]
                    top_ency = via_info['top_ency'][0]
                    gm1_delta = gv0_h // 2 + top_ency
                    m1_w = gv0_w + 2 * top_encx
                    bot_encx = (m1_w - gv0_w) // 2
                    bot_ency = (mp_h - gv0_h) // 2
                    # bottom MP
                    mp_yt = md_yb - mp_md_sp
                    mp_yb = mp_yt - mp_h
                    mp_yc = (mp_yt + mp_yb) // 2
                    m1_yb = mp_yc - gm1_delta
                    mp_y_list = [(mp_yb, mp_yt)]
                    # top MP
                    mp_yb = md_yt + mp_md_sp
                    mp_yt = mp_yb + mp_h
                    mp_yc = (mp_yb + mp_yt) // 2
                    m1_yt = mp_yc + gm1_delta
                    mp_y_list.append((mp_yb, mp_yt))

                    # draw MP
                    for fgl in range(0, fg + 1, 2):
                        mp_xl = xshift + fgl * sd_pitch - sd_pitch // 2 + lch_unit // 2 - mp_po_ovl
                        mp_xr = xshift + (fgl + 2) * sd_pitch + sd_pitch // 2 - lch_unit // 2 + mp_po_ovl
                        for mp_yb, mp_yt in mp_y_list:
                            template.add_rect('LiPo', BBox(mp_xl, mp_yb, mp_xr, mp_yt, res, unit_mode=True))

                    # draw M1 and VIA0
                    via_type = 'M1_LiPo'
                    enc1 = [bot_encx, bot_encx, bot_ency, bot_ency]
                    enc2 = [top_encx, top_encx, top_ency, top_ency]
                    for idx in range(0, fg + 1, 2):
                        m1_xc = xshift + idx * sd_pitch
                        template.add_rect('M1', BBox(m1_xc - m1_w // 2, m1_yb, m1_xc + m1_w // 2, m1_yt, res,
                                                     unit_mode=True))
                        for mp_yb, mp_yt in mp_y_list:
                            mp_yc = (mp_yb + mp_yt) // 2
                            template.add_via_primitive(via_type, [m1_xc, mp_yc], enc1=enc1, enc2=enc2, unit_mode=True)

        return has_od

    @classmethod
    def _draw_ds_via(cls, template, wire_pitch, od_yc, num_seg, via_info, sbot, sdir, ddir,
                     m1_x_list, m3_x_list, xshift=0):
        # Note: m2_x_list is guaranteed to contain m3_x_list

        res = cls.tech_constants['resolution']
        v0_sp = cls.tech_constants['v0_sp']

        nv0 = via_info['num_v0']
        m1_h = via_info['m1_h']
        m2_h = via_info['m2_h']
        m3_h = via_info['m3_h']
        md_encx, m1_bot_encx, m2_bot_encx = via_info['bot_encx']
        m1_encx, m2_encx, m3_encx = via_info['top_encx']
        md_ency, m1_bot_ency, m2_bot_ency = via_info['bot_ency']
        m1_ency, m2_ency, m3_ency = via_info['top_ency']
        v0_h, v1_h, v2_h = via_info['h']

        # draw via to M1
        via_type = 'M1_LiAct'
        enc1 = [md_encx, md_encx, md_ency, md_ency]
        enc2 = [m1_encx, m1_encx, m1_ency, m1_ency]
        template.add_via_primitive(via_type, [xshift, od_yc], num_rows=nv0, sp_rows=v0_sp,
                                   enc1=enc1, enc2=enc2, nx=num_seg + 1, spx=wire_pitch, unit_mode=True)
        # add M1
        m1_yb = od_yc - m1_h // 2
        m1_yt = m1_yb + m1_h
        m1_warrs = []
        for idx in range(num_seg + 1):
            m1_xc = xshift + idx * wire_pitch
            tidx = template.grid.coord_to_nearest_track(1, m1_xc, unit_mode=True)
            cur_warr = template.add_wires(1, tidx, m1_yb, m1_yt, unit_mode=True)
            if m1_xc in m1_x_list:
                m1_warrs.append(cur_warr)

        bot_yc = m1_yb + m1_bot_ency + v1_h // 2
        top_yc = m1_yt - m1_bot_ency - v1_h // 2

        # draw via to M2/M3 and add metal/ports
        v1_enc1 = [m1_bot_encx, m1_bot_encx, m1_bot_ency, m1_bot_ency]
        v1_enc2 = [m2_encx, m2_encx, m2_ency, m2_ency]
        v2_enc1 = [m2_bot_encx, m2_bot_encx, m2_bot_ency, m2_bot_ency]
        v2_enc2 = [m3_encx, m3_encx, m3_ency, m3_ency]
        m3_warrs = []
        m2b_x = [None, None]  # type: List[int]
        m2t_x = [None, None]  # type: List[int]
        for xloc in m3_x_list:
            parity = xloc // wire_pitch
            if parity % 2 == 0:
                vdir = sdir
                if sbot:
                    via_yc = bot_yc
                    m2x_list = m2b_x
                else:
                    via_yc = top_yc
                    m2x_list = m2t_x
            else:
                vdir = ddir
                if sbot:
                    via_yc = top_yc
                    m2x_list = m2t_x
                else:
                    via_yc = bot_yc
                    m2x_list = m2b_x
            if vdir == 0:
                m_yt = via_yc + v2_h // 2 + enc2[2]
                m_yb = m_yt - m3_h
            elif vdir == 2:
                m_yb = via_yc - v2_h // 2 - enc2[3]
                m_yt = m_yb + m3_h
            else:
                m_yb = via_yc - m3_h // 2
                m_yt = m_yb + m3_h

            cur_xc = xshift + xloc
            m2x_list[0] = cur_xc if m2x_list[0] is None else min(cur_xc, m2x_list[0])
            m2x_list[1] = cur_xc if m2x_list[1] is None else max(cur_xc, m2x_list[1])

            loc = [cur_xc, via_yc]
            template.add_via_primitive('M2_M1', loc, cut_height=v1_h, enc1=v1_enc1, enc2=v1_enc2, unit_mode=True)
            template.add_via_primitive('M3_M2', loc, cut_height=v2_h, enc1=v2_enc1, enc2=v2_enc2, unit_mode=True)

            tr_idx = template.grid.coord_to_track(3, cur_xc, unit_mode=True)
            m3_warrs.append(template.add_wires(3, tr_idx, m_yb, m_yt, unit_mode=True))

        for (m2_xl, m2_xr), m2_yc in ((m2b_x, bot_yc), (m2t_x, top_yc)):
            m2_yb = m2_yc - m2_h // 2
            m2_yt = m2_yb + m2_h
            template.add_rect('M2', BBox(m2_xl, m2_yb, m2_xr, m2_yt, res, unit_mode=True))

        return m1_warrs, m3_warrs
