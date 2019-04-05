# Copyright © 2019 Adobe, Inc.
# Author: Miguel Sousa
"""
Creates a sans-color emoji font (OTF or TTF) from b&w SVG files.
"""
import argparse
from collections import deque
import glob
import logging
import os
import re
import sys

from fontTools.feaLib.builder import addOpenTypeFeatures
from fontTools.fontBuilder import FontBuilder
from fontTools.misc.psCharStrings import T2CharString
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.svgLib.path import SVGPath

FILE_PREFIX = 'emoji_'

COPYRIGHT = 'Copyright 2013 Google Inc.'
TRADEMARK = 'Noto is a trademark of Google Inc.'
FAMILY_NAME = 'Noto Emoji'
STYLE_NAME = 'Regular'
FULL_NAME = FAMILY_NAME
PS_NAME = 'NotoEmoji'
MANUFACTURER = 'Google Inc. & Adobe Inc.'
DESIGNER = 'Google Inc.'
VENDOR = 'GOOG'
VENDOR_URL = 'http://www.google.com/get/noto/'
DESIGNER_URL = VENDOR_URL
LICENSE = ('This Font Software is licensed under the SIL Open Font License, '
           'Version 1.1. This Font Software is distributed on an "AS IS" '
           'BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either '
           'express or implied. See the SIL Open Font License for the '
           'specific language, permissions and limitations governing your '
           'use of this Font Software.')
LICENSE_URL = 'http://scripts.sil.org/OFL'
FSTYPE = 0  # Installable embedding

EM = 2048
SVG_SIZE = 128
ASCENT = EM
DESCENT = 0


RE_UNICODE = re.compile(r'^u[0-9a-f]{4,5}$', re.IGNORECASE)
RE_REVISION = re.compile(r'^[0-9]{1,3}\.[0-9]{3}$')

VALID_1STCHARS = tuple('_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz')
VALID_CHARS = VALID_1STCHARS + tuple('.0123456789')

log = logging.getLogger('make_bw_font')


def draw_notdef(pen):
    em_10th = EM / 10
    pen.moveTo((em_10th * 2, em_10th))
    pen.lineTo((em_10th * 8, em_10th))
    pen.lineTo((em_10th * 8, em_10th * 9))
    pen.lineTo((em_10th * 2, em_10th * 9))
    pen.closePath()
    pen.moveTo((em_10th * 3, em_10th * 2))
    pen.lineTo((em_10th * 3, em_10th * 8))
    pen.lineTo((em_10th * 7, em_10th * 8))
    pen.lineTo((em_10th * 7, em_10th * 2))
    pen.closePath()


def glyph_name_is_valid(gname, fpath):
    """
    Validates a string meant to be used as a glyph name, following the rules
    defined at https://adobe-type-tools.github.io/afdko/...
                       OpenTypeFeatureFileSpecification.html#2.f.i
    Returns True if the glyph name is valid and False otherwise.
    """
    if not gname:
        log.warning("Unable to get a glyph name from file '{}'.".format(fpath))
        return False
    elif gname[0] not in VALID_1STCHARS:
        log.warning("Glyph name made from file '{}' starts with an invalid "
                    "character '{}'.".format(fpath, gname[0]))
        return False
    elif not all([char in VALID_CHARS for char in tuple(gname)]):
        log.warning("Glyph name made from file '{}' contains one or more "
                    "invalid characters.".format(fpath))
        return False
    return True


def get_trimmed_glyph_name(gname, num):
    """
    Glyph names cannot have more than 31 characters.
    See https://docs.microsoft.com/en-us/typography/opentype/spec/...
               recom#39post39-table
    Trims an input string and appends a number to it.
    """
    suffix = '_{}'.format(num)
    return gname[:31 - len(suffix)] + suffix


def make_font(file_paths, out_dir, revision, gsub_path):
    cmap, gorder, validated_fpaths = {}, deque(), []
    for fpath in file_paths:
        # build glyph order
        fname = os.path.splitext(os.path.basename(fpath))[0]  # trim extension
        if fname.startswith(FILE_PREFIX):
            gname = fname[len(FILE_PREFIX):]
        else:
            gname = fname
        # validate glyph name
        if not glyph_name_is_valid(gname, fpath):
            continue
        # skip any duplicates and 'space'
        if gname in gorder or gname == 'space':
            log.warning("Skipped file '{}'. The glyph name derived from it "
                        "is either a duplicate or 'space'.".format(fpath))
            continue
        # limit the length of glyph name to 31 chars
        if len(gname) > 31:
            num = 0
            trimmed_gname = get_trimmed_glyph_name(gname, num)
            while trimmed_gname in gorder:
                num += 1
                trimmed_gname = get_trimmed_glyph_name(trimmed_gname, num)
            gorder.append(trimmed_gname)
            log.warning("Glyph name '{}' was trimmed to 31 characters: "
                        "'{}'.".format(gname, trimmed_gname))
        else:
            gorder.append(gname)
        validated_fpaths.append(fpath)

        # build cmap
        if RE_UNICODE.match(gname):
            uni_int = int(gname[1:], 16)  # trim leading 'u'
            cmap[uni_int] = gname

    fb = FontBuilder(EM, isTTF=False)
    fb.font['head'].fontRevision = float(revision)

    cs_dict = {}
    for i, svg_file_path in enumerate(validated_fpaths):
        pen = T2CharStringPen(EM, None)
        svg = SVGPath(svg_file_path,
                      transform=(EM / SVG_SIZE, 0, 0, -EM / SVG_SIZE, 0, EM))
        svg.draw(pen)
        cs = pen.getCharString()
        cs_dict[gorder[i]] = cs

    # add '.notdef' and 'space'
    gorder.extendleft(reversed(['.notdef', 'space']))
    pen = T2CharStringPen(EM, None)
    draw_notdef(pen)
    cs_dict.update({'.notdef': pen.getCharString(),
                    'space': T2CharString(program=['endchar'])})
    cmap.update({32: 'space', 160: 'space'})  # U+0020 & U+00A0)

    fb.setupGlyphOrder(gorder)
    fb.setupCharacterMap(cmap)
    fb.setupCFF(PS_NAME, {'version': revision,
                          'Notice': TRADEMARK,
                          'Copyright': COPYRIGHT,
                          'FullName': FULL_NAME,
                          'FamilyName': FAMILY_NAME,
                          'Weight': STYLE_NAME}, cs_dict, {})

    advance_widths = {gname: EM for gname in gorder}

    glyphs_lsb = {}
    for gname, cs in cs_dict.items():
        gbbox = cs.calcBounds(None)
        if gbbox:
            glyphs_lsb[gname] = gbbox[0]
        else:
            glyphs_lsb[gname] = 0

    metrics = {}
    for gname, advanceWidth in advance_widths.items():
        metrics[gname] = (advanceWidth, glyphs_lsb[gname])
    fb.setupHorizontalMetrics(metrics)

    fb.setupHorizontalHeader(ascent=ASCENT, descent=DESCENT)

    VERSION_STRING = 'Version {};{}'.format(revision, VENDOR)
    name_strings = dict(
        copyright=COPYRIGHT,         # ID 0
        familyName=FAMILY_NAME,      # ID 1
        styleName=STYLE_NAME,        # ID 2
        fullName=FULL_NAME,          # ID 4
        version=VERSION_STRING,      # ID 5
        psName=PS_NAME,              # ID 6
        trademark=TRADEMARK,         # ID 7
        manufacturer=MANUFACTURER,   # ID 8
        designer=DESIGNER,           # ID 9
        vendorURL=VENDOR_URL,        # ID 11
        designerURL=DESIGNER_URL,    # ID 12
        licenseDescription=LICENSE,  # ID 13
        licenseInfoURL=LICENSE_URL,  # ID 14
    )
    fb.setupNameTable(name_strings, mac=False)

    fb.setupOS2(fsType=FSTYPE, achVendID=VENDOR,
                usWinAscent=EM, usWinDescent=DESCENT,
                sTypoAscender=EM, sTypoDescender=DESCENT)

    fb.setupPost()
    fb.setupDummyDSIG()

    if gsub_path:
        addOpenTypeFeatures(fb.font, gsub_path, tables=['GSUB'])

    fb.save(os.path.join(out_dir, '{}.otf'.format(PS_NAME)))


def _validate_dir_path(path_str):
    valid_path = os.path.abspath(os.path.realpath(path_str))
    if not os.path.isdir(valid_path):
        raise argparse.ArgumentTypeError(
            "{} is not a valid directory path.".format(path_str))
    return _normalize_path(path_str)


def _validate_file_path(path_str):
    valid_path = os.path.abspath(os.path.realpath(path_str))
    if not os.path.isfile(valid_path):
        raise argparse.ArgumentTypeError(
            "{} is not a valid file path.".format(path_str))
    return _normalize_path(path_str)


def _normalize_path(path_str):
    return os.path.normpath(path_str)


def _validate_revision_number(rev_str):
    if not RE_REVISION.match(rev_str):
        raise argparse.ArgumentTypeError(
            "The revision number must use this format: 123.456")
    return rev_str


def main(args=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '-v',
        '--verbose',
        help='increase the logger verbosity. Multiple -v '
             'options are allowed.',
        action='count',
        default=0
    )
    parser.add_argument(
        'in_dir',
        help='input directory containing SVG files',
        metavar='DIR',
        type=_validate_dir_path,
    )
    parser.add_argument(
        '-o',
        '--out-dir',
        help='directory to save the font in. Defaults to input directory.',
        metavar='DIR',
        type=_normalize_path,
    )
    parser.add_argument(
        '-r',
        '--revision',
        help="the font's revision number. Defaults to %(default)s",
        type=_validate_revision_number,
        default='0.001',
    )
    parser.add_argument(
        '--gsub',
        help='path to GSUB features file',
        type=_validate_file_path,
    )
    opts = parser.parse_args(args)

    if not opts.verbose:
        level = "WARNING"
    elif opts.verbose == 1:
        level = "INFO"
    else:
        level = "DEBUG"
    logging.basicConfig(level=level)

    file_paths = sorted(
        glob.iglob(os.path.join(opts.in_dir, '*.[sS][vV][gG]')))
    file_count = len(file_paths)

    if not file_count:
        log.warning('Failed to match any SVG files.')
        return 1

    log.info("Found {} SVG files in '{}'.".format(file_count, opts.in_dir))

    if opts.out_dir:
        out_path = os.path.abspath(os.path.realpath(opts.out_dir))
        # create directory if it doesn't exist
        if not os.path.exists(out_path):
            os.makedirs(out_path)
        # the path exists but it's NOT a directory
        elif not os.path.isdir(out_path):
            log.error("'{}' is not a directory.".format(opts.out_dir))
            return 1
        out_dir = opts.out_dir
    else:
        out_dir = opts.in_dir

    make_font(file_paths, out_dir, opts.revision, opts.gsub)


if __name__ == "__main__":
    sys.exit(main())
