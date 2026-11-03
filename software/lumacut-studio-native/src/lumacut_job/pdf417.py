"""PDF417 (ISO/IEC 15438) as vector objects for engraving – pure Python.

PDF417 is the stacked 2D code of ID cards, boarding passes, shipping labels and
parts tags: 3–90 rows of 1–30 data columns, each codeword 17 modules wide
(4 bars, 4 spaces) between a start pattern, left/right row indicators and a stop
pattern. Compact PDF417 (truncated) drops the right row
indicator and shortens the stop pattern to one bar – narrower, but less robust.

High-level encodation (:func:`encode_data`) splits the bytes into segments:
runs of 13+ digits go to Numeric compaction (44 digits → 15 codewords), runs of
text characters to Text compaction (two characters per codeword; the submodes
Alpha, Lower, Mixed and Punct are chosen by a shortest-path search over
latches and shifts), the rest to Byte compaction (6 bytes → 5 codewords, single
bytes inside text with the Byte Shift 913). Text that is not ASCII is written
as UTF-8 behind ECI 26 (codeword 927).

Error correction is Reed-Solomon over GF(929) with 2^(s+1) check codewords
for level s = 0…8; automatic = the ISO recommendation by data length
(1–40 data codewords: level 2, 41–160: 3, 161–320: 4, 321–863: 5). The
codeword bar/space patterns of the three clusters are the tables of ISO/IEC
15438 (same values as the zxing reference encoder), stored compactly below.

Output style is the one of :mod:`lumacut_job.datamatrix`: ``width_mm`` is the
width of the symbol without quiet zone, the row height is ``row_height`` times
the module width (ISO: at least 3); the quiet zone (in module widths, on all
four sides; ISO: 2) stays light (normal) or is engraved together with the light
modules (inverted).
"""

from __future__ import annotations

import base64
import math
from dataclasses import dataclass
from functools import lru_cache

from lumacut_canvas.model import Shape, new_id
from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM

AUTO = 0                          # columns: automatic
AUTO_ECC = -1                     # error correction level: ISO recommendation
COLUMNS_RANGE = (1, 30)
ROWS_RANGE = (3, 90)
ECC_LEVELS = tuple(range(9))
MAX_CODEWORDS = 928               # data (incl. length descriptor) + check codewords
MIN_MODULE_MM = 0.4               # narrower bars burn shut on wood with a diode laser
HARD_MIN_MODULE_MM = 0.2
WIDTH_RANGE = (5.0, WORK_WIDTH_MM)
ROW_HEIGHT_RANGE = (2.0, 10.0)    # row height / module width
DEFAULT_ROW_HEIGHT = 3.0
QUIET_RANGE = (0, 10)
DEFAULT_QUIET = 2
PREFERRED_RATIO = 3.0             # automatic columns: symbol width / height closest to this

# --- codeword patterns ----------------------------------------------------------------

START_PATTERN = 0x1FEA8           # 17 modules: 8 bar, 1 space, 1 bar, … (81111113)
STOP_PATTERN = 0x3FA29            # 18 modules (711311121)
_TABLE_B64 = (
    "auB1eHq+anB1PHqfVGBqOFQwKCBUGCgQVuBreHW+VnBrPHWfLGBWOCwwLuBXeGu+LnBXPGufLjhXHi94V74vPFef"
    "L756/WlwdLx6X1JgaTh0nlIwaRwkIFIYaQ4kEFIMJAhTcGm8dN8mYFM4aZ4mMFMcaY8mGFMOJ3BTvGnfJzhTnicc"
    "U48nvFPfJ54nj1FgaLh0XlEwaJx0TyIgURhojiIQUQwiCCIEI2BRuGjeIzBRnGjPIxhRjiMMIwYjuFHeI5xRzyOO"
    "I95QsGhcdC8hIFCYaE4hEFCMaEchCFCGIQRQgyGwUNxobyGYUM4hjFDHIYYhg1DvIccgoFBYaC4gkFBMaCcgiFBG"
    "IIRQQyCCINggzCDGIFBoF1AmUCMgQWVwcrx5X0pgZThynkowZRxyjxQgShgUEEtwZbxy3xZgSzhlnhYwSxwWGBYM"
    "F3BLvGXfFzhLnhccFw4XvEvfF54X321gdrh7Xm0wdpx7T1ogbRh2jloQbQx2h1oIbQZJYGS4cl5bYEkwZJxyT1sw"
    "bZx2zzYgEhBJDGSHNhBbDDYIE2BJuGTeN2ATMEmcZM83MFucbc83GBMMNwwTuEneN7gTnEnPN5xbzzeOE9433hPP"
    "N89ssHZcey9ZIGyYdk5ZEGyMdkdZCGyGWQRZAkiwZFxyL1mwSJhkTjMgERBszmRHMxARCEiGMwhZhkiDEQIRsEjc"
    "ZG8zsBGYSM4zmFnOSMczjBGGEYMR3EjvM9wRzjPOEcczxzPvWKBsWHYuWJBsTHYnWIhsRliEbENYgliBEKBIWGQu"
    "MaAQkEhMZCcxkFjMbGcxiBCESEMxhFjDMYIQ2EhuMdgQzEhnMcxY5zHGEMMxwzHuMedYUGwsdhdYSGwmWERsI1hC"
    "WEEQUEgsZBcw0BBISCYwyFhmSCMwxBBCMMIQQRBsMOww5jDjbBZsE1ghSBYQJDBkMGIwYUVgYrhxXkUwYpwKIEUY"
    "Yo4KEEUMCggKBAtgRbhi3gswRZxizwsYRY4LDAsGC7hF3gucRc8LjgveC89msHNcea9NIGaYc05NEGaMc0dNCGaG"
    "TQRmg0SwYlxxL02wRJhiThsgCRBmzmJHGxBNjESGGwgJBBsECbBE3GJvG7AJmGbvG5hNzkTHG4wJhhuGCdxE7xvc"
    "Cc4bzgnHCe8b726gd1h7rm6Qd0x7p26Id0ZuhHdDboJMoGZYcy5doEyQd25zJ12Qbsx3Z12ITIRmQ12EbsNMgQig"
    "RFhiLhmgCJBETGInO6AZkEzMZmc7kF3MbudEQzuIGYRMwzuECIEI2ERuGdgIzERnO9gZzEznO8xd5wjDGcMI7hnu"
    "COc77hnnblB3LHuXbkh3Jm5EdyNuQm5BTFBmLHMXXNBMSHc3XMhuZmYjXMRMQlzCTEFcwQhQRCxiFxjQCEhEJjnQ"
    "GMhMZkQjOchc5ghCOcQYwghBGMEIbEQ3GOwIZjnsGOYIYznmGOMIdzn3bih3Fm4kdxNuIm4hTChmFlxoTCRmE1xk"
    "bjNcYkwhXGEIKEQWGGgIJEQTOOgYZEwzOORccwghOOIYYTjhGHY49jjzdwtuEWYLTBJMEQgUGDQ4dAgRGDFCsAUg"
    "QpgFEEKMYUcFCEKGBQRCgwWwQtxhbwWYQs4FjELHBYYFgwXcQu8FzgXHBe9GoGNYca5GkGNMRohjRkaEY0NGggSg"
    "QlhhLg2gBJBjbmEnDZBGzGNnDYgEhEJDDYRGwwSBBNhCbg3YBMxCZw3MRucNxgTDBO4N7gTnDednUHOseddnSHOm"
    "Z0Rzo2dCZ0FGUGMsTtBGSGMmTshnZmMjTsRGQk7CRkFOwQRQQiwM0ARIYzcd0AzIRmZCIx3ITuYEQh3EDMIEQQzB"
    "BGxCNwzsBGYd7AzmBGMd5gzjBHcM9x33d6h71neke9N3onehZyhzlm9od7Zzk29kd7NvYmchb2FGKGMWTmhGJGMT"
    "XuhOZGczXuRvc0YhXuJOYV7hBChCFgxoBCRCExzoDGRGMz3oHOROcwQhPeRe8wxhPeIENgx2BDMc9gxzPfYc8z3z"
    "d5R7y3eSd5FnFHOLbzR3m28yZxFvMUYUYwtONEYSXnROMkYRXnJOMV5xBBRCCww0RhscdAwyBBE89BxyDDE88hxx"
    "PPEMOzz7d4lvGm8ZThpeOl45DBocOjx6PHkCoAKQQUwCiAKEAoIC2ALMAsYCwwLuAudDUENIYaZDRGGjQ0JDQQJQ"
    "QSwG0ENsQSYGyENmBsRDYwbCAkEGwQJsQTcG7EN3BuYCYwbjAncG92OoY6RjomOhQyhHaGO2YZNHZGOzR2JDIUdh"
    "AigGaAIkQRMO6AZkAiIO5AZiAiEO4gZhAjYGdgIzDvYGcw7zc9Rz0nPRY5RntHPbZ7JjkWexQxRhi0c0Y5tPdEcy"
    "QxFPckcxT3ECFEELBjRDGw50BjICER70DnIGMR7yDnECGwY7Dnse+3vqe+lzynfac8l32WOKZ5pjiW+6Z5lvuUMK"
    "RxpDCU86RxlfenqwfVx1IHqYfU51EHqMfUd1CHqGdQR6g3UCdbB63H1vayB1mHrOaxB1jHrHawh1hmsEdYNrAmuw"
    "ddx671cga5h1zlcQa4x1x1cIa4ZXBGuDVwJXsGvcde8vIFeYa84vEFeMa8cvCFeGLwRXgy+wV9xr7y+YV84vjFfH"
    "L4Yv3FfvL84vx3Sgelh9LnSQekx9J3SIekZ0hHpDdIJ0gWmgdNh6bmmQdMx6Z2mIdMZphHTDaYJpgVOgadh07lOQ"
    "acx051OIacZThGnDU4JTgSegU9hp7ieQU8xp5yeIU8YnhFPDJ4In2FPuJ8xT5yfGJ8Mn7ifndFB6LH0XdEh6JnRE"
    "eiN0QnRBaNB0bHo3aMh0ZmjEdGNowmjBUdBo7HR3Ucho5lHEaONRwlHBI9BR7Gj3I8hR5iPEUeMjwiPBI+xR9yPm"
    "I+Mj93QoehZ0JHoTdCJ0IWhodDZoZHQzaGJoYVDoaHZQ5GhzUOJQ4SHoUPYh5FDzIeIh4SH2IfN0FHoLdBJ0EWg0"
    "dBtoMmgxUHRoO1ByUHEg9FB7IPIg8XQKdAloGmgZUDpQOXKgeVh8rnKQeUx8p3KIeUZyhHlDcoJygWWgcth5bmWQ"
    "csx5Z2WIcsZlhHLDZYJlgUugZdhy7kuQZcxy50uIZcZLhGXDS4JLgRegS9hl7heQS8xl5xeIS8YXhEvDF4IX2Evu"
    "F8xL5xfGF8MX7hfne1B9rDX4e0h9pjT8e0R9ozR+e0J7QXJQeSx8l3bQckh9t3bIe2Z5I3bEckJ2wnJBdsFk0HJs"
    "eTdt0GTIcmZtyHbmcmNtxGTCbcJkwW3BSdBk7HJ3W9BJyGTmW8ht5mTjW8RJwlvCScFbwRPQSexk9zfQE8hJ5jfI"
    "W+ZJ4zfEE8I3whPBE+xJ9zfsE+Y35hPjN+MT93sofZYy/HskfZMyfnsiMj97IXIoeRZ2aHIkeRN2ZHszdmJyIXZh"
    "ZGhyNmzoZGRyM2zkdnNs4mRhbOFI6GR2WehI5GRzWeRs81niSOFZ4RHoSPYz6BHkSPMz5FnzM+IR4TPhEfYz9hHz"
    "M/N7FH2LMX57EjE/exFyFHkLdjR7G3YychF2MWQ0chtsdGQybHJkMWxxSHRkO1j0bHtY8khxWPEQ9Eh7MfQQ8jHy"
    "EPEx8RD7Mft7CjC/ewlyCnYacgl2GWQabDpkGWw5SDpYekg5WHkQejD6EHkw+XsFcgV2DWQNbB1IHVg9cVB4rHxX"
    "cUh4pnFEeKNxQnFBYtBxbHi3YshxZmLEcWNiwmLBRdBi7HF3Rchi5kXEYuNFwkXBC9BF7GL3C8hF5gvEReMLwgvB"
    "C+xF9wvmC+ML93mofNYa/HmkfNMafnmiGj95oXEoeJZzaHEkeJNzZHmzc2JxIXNhYmhxNmboYmRxM2bkc3Nm4mJh"
    "ZuFE6GJ2TehE5GJzTeRm803iROFN4QnoRPYb6AnkRPMb5E3zG+IJ4RvhCfYb9gnzG/N91Dr4XX590jp8XT990To+"
    "Oh95lHzLGX57tH3bO34ZP3uyeZE7P3uxcRR4i3M0cRJ3dHu7cRF3cnMxd3FiNHEbZnRiMm70ZnJiMW7yZnFu8UR0"
    "YjtM9ERyXfRM8kRxXfJM8V3xCPREexn0CPI79BnyCPE78hnxO/EI+xn7fco5fFy/fck5PjkfeYoYv3uaeYk5v3uZ"
    "cQpzGnEJdzpzGXc5YhpmOmIZbnpmOW55RDpMekQ5XPpMeVz5CHoY+gh5OfoY+Tn5fcU4vjifeYV7jXEFcw13HWIN"
    "Zh1uPUQdTD1cfQg9GH04/ThfcKh4VnCkeFNwonChYWhwtmFkcLNhYmFhQuhhdkLkYXNC4kLhBehC9gXkQvMF4gXh"
    "BfYF83jUfGsNfnjSDT940XCUeEtxtHCScbJwkXGxYTRwm2N0YTJjcmExY3FCdGE7RvRCckbyQnFG8QT0QnsN9ATy"
    "DfIE8Q3xBPsN+3zqHXxOv3zpHT4dH3jKDL952njJHb952XCKcZpwiXO6cZlzuWEaYzphGWd6YzlneUI6RnpCOU76"
    "RnlO+QR6DPoEeR36DPkd+T14Xr49PF6fPR49D3zlHL597T2+HJ89n3jFec173XCFcY1znXe9YQ1jHWc9b31CHUY9"
    "Tn1e/QQ9DH0c/Ty8Xl88njyPHF883zxePE88L3BUcFJwUWC0cFtgsmCxQXRgu0FyQXEC9EF7AvIC8QL7eGoGv3hp"
    "cEpw2nBJcNlgmmG6YJlhuUE6Q3pBOUN5AnoG+gJ5Bvl8dQ6+Dp94ZXjtcEVwzXHdYI1hnWO9QR1DPUd9Aj0GfQ79"
    "HrxPXx6eHo8OXx7fPrhfXj6cX08+jj6HHl4+3h5PPs8+XF8vPk4+Rx4vPm8+Lj4nPhdgWmBZQLpAuQF6AXlwbWBN"
    "YN1AnUG9AT0DfQdfD14PTx9cT68fTh9HDy8fbz9YX64/TF+nP0Y/Qx8uP24fJz9nPyxflz8mPyMfFz83PxY/Ewev"
    "D64Ppx+sT9cfph+jD5cftx+WH5NV8Gr8KeBU+Gp+KPBUfGo/KHhUPig8fWgt8Fb8fWQs+FZ+fWIsfFY/fWEsPnro"
    "fXYu/HrkfXMufnriLj964XXoevZ15HrzdeJ14WvodfZr5HXza+Jr4Vfoa/ZX5GvzV+Il4FL4aX4k8FJ8aT8keFI+"
    "JDxSHyQefTQm+FN+fTImfFM/fTEmPiYfenR9Oyd+enInP3pxdPR6e3TydPFp9HT7afJp8VP0aftT8lPxIvBRfGi/"
    "InhRPiI8UR8iHiIPfRojfFG/fRkjPiMfejojv3o5dHp0eWj6aPlR+lH5IXhQviE8UJ8hHiEPfQ0hviGfeh10PWh9"
    "ILxQXyCeII8g3yBeIE8V4Er4ZX4U8Ep8ZT8UeEo+FDxKHxQefLQW+Et+fLIWfEs/fLEWPhYfeXR8uxd+eXIXP3lx"
    "cvR5e3LycvFl9HL7ZfJl8Uv0ZftL8kvxWvBtfHa/NOBaeG0+NHBaPG0fNDhaHjQcWg80DhLwSXxkvzbwEnhJPjZ4"
    "Wz5JHzY8Eh42HhIPNg98mhN8Sb99unyZN3wTPn25Nz4THzcfeToTv3t6eTk3v3t5cnp2+nJ5dvlk+m36ZPlt+Un6"
    "Sfky4Fl4bL4ycFk8bJ8yOFkeMhxZDzIOMgcReEi+M3gRPEifMzxZnzMeEQ8zD3yNEb59nTO+EZ8zn3kdez1yPXZ9"
    "ZH1s/Uj9MXBYvGxfMThYnjEcWI8xDjEHELxIXzG8EJ4xnhCPMY8Q3zHfMLhYXjCcWE8wjjCHEF4w3hBPMM8wXFgv"
    "ME4wRxAvMG8wLjAnCvBFfGK/CnhFPgo8RR8KHgoPfFoLfEW/fFkLPgsfeLoLv3i5cXpxeWL6YvlF+kX5GuBNeGa+"
    "GnBNPGafGjhNHhocTQ8aDhoHCXhEvht4CTxEnxs8TZ8bHgkPGw98TQm+fN0bvgmfG594nXm9cT1zfWJ9Zv1E/V1w"
    "brx3XzpgXThunjowXRxujzoYXQ46DF0HOgYZcEy8Zl87cBk4TJ47OF2eTI87HBkOOw4ZBzsHCLxEXxm8CJ47vBme"
    "CI87nhmPO48I3xnfO985YFy4bl45MFycbk85GFyOOQxchzkGOQMYuExeObgYnExPOZxczzmOGIc5hwheGN4ITzne"
    "GM85zziwXFxuLziYXE44jFxHOIY4gxhcTC843BhOOM4YRzjHCC8YbzjvOFhcLjhMXCc4RjhDGC44bhgnOGc4LFwX"
    "OCY4IxgXODc4FjgTBXhCvgU8Qp8FHgUPBb4Fn3hdcL1hfUL9DXBGvGNfDThGng0cRo8NDg0HBLxCXw28BJ4NngSP"
    "DY8E3w3fHWBOuGdeHTBOnGdPHRhOjh0MTocdBh0DDLhGXh24DJxGTx2cDI4djgyHHYcEXgzeBE8d3gzPHc9esG9c"
    "d689IF6Yb049EF6Mb0c9CF6GPQRegz0CHLBOXGcvPbAcmE5OPZhezk5HPYwchj2GHIM9gwxcRi8c3AxOPdwczgxH"
    "Pc4cxz3HBC8MbxzvPe88oF5Yby48kF5Mbyc8iF5GPIReQzyCPIEcWE4uPNgcTE4nPMxeZzzGHEM8wwwuHG4MJzzu"
    "HGc85zxQXixvFzxIXiY8RF4jPEI8QRwsThc8bBwmPGYcIzxjDBccNzx3PCheFjwkXhM8IjwhHBY8NhwTPDM8FF4L"
    "PBI8ERwLPBsCvEFfAp4CjwLfBrhDXgacQ08GjgaHAl4G3gJPBs8OsEdcY68OmEdODoxHRw6GDoMGXEMvDtwGTg7O"
    "BkcOxwIvBm8O7x6gT1hnrh6QT0xnpx6IT0YehE9DHoIegQ5YRy4e2A5MRycezE9nHsYOQx7DBi4ObgYnHu4OZx7n"
    "X1BvrHfXX0hvpl9Eb6NfQl9BHlBPLGeXPtAeSE8mPshfZk8jPsQeQj7CHkE+wQ4sRxcebA4mPuweZg4jPuYeYz7j"
    "BhcONx53PvdfKG+WXyRvk18iXyEeKE8WPmgeJE8TPmRfMz5iHiE+YQ4WHjYOEz52HjM+c18Ub4tfEl8RHhRPCz40"
    "HhI+Mh4RPjEOCx4bPjtfCl8JHgo+Gh4JPhkBXgFPA1xBrwNOA0cBLwNvB1hDrgdMQ6cHRgdDAy4HbgMnB2cPUEes"
    "Y9cPSEemD0RHow9CD0EHLEOXD2xHtw9mByMPYwMXBzcPd0+oZ9ZPpGfTT6JPoQ8oR5YfaE+2R5MfZA8iH2IPIR9h"
    "BxYPNgcTH3YPMx9zb9R362/Sb9FPlGfLX7RPkl+yT5FfsQ8UR4sfNA8SP3QfMg8RP3IfMT9xBwsPGx87P3tvym/J"
    "T4pfmk+JX5kPCh8aDwk/Oh8ZPzlvxU+FX40PBR8NPx0BrgGnA6xB1wOmA6MBlwO3B6hD1gekQ9MHogehA5YHtgOT"
    "B7NH1GPrR9JH0QeUQ8sPtEfbD7IHkQ+xA4sHmw+7Z+pn6UfKT9pHyU/ZB4oPmgeJH7oPmR+5Z+VHxU/NB4UPjR+d"
    "AdYB0wPUQesD0gPRAcsD20PqQ+kDygfaA8kH2WP1"
)


@lru_cache(maxsize=None)
def _table() -> tuple[tuple[int, ...], ...]:
    raw = base64.b64decode("".join(_TABLE_B64))
    words = [((raw[2 * i] << 8 | raw[2 * i + 1]) << 1) | 0x10000 for i in range(len(raw) // 2)]
    return tuple(tuple(words[k * 929:(k + 1) * 929]) for k in range(3))


def pattern(cluster: int, codeword: int) -> int:
    """17-bit pattern (MSB first, 1 = bar) of ``codeword`` in cluster 0, 1 or 2 (= 0, 3, 6)."""
    return _table()[cluster][codeword]


def widths(p: int, length: int = 17) -> list[int]:
    """Bar/space widths of a pattern (starts with a bar)."""
    s = format(p, f"0{length}b")
    out, run = [], 1
    for a, b in zip(s, s[1:]):
        if a == b:
            run += 1
        else:
            out.append(run)
            run = 1
    out.append(run)
    return out


# --- high-level encodation -------------------------------------------------------------

LATCH_TEXT, LATCH_BYTE, LATCH_NUMERIC, SHIFT_BYTE, LATCH_BYTE6, ECI_CHARSET = (
    900, 901, 902, 913, 924, 927)
PAD = 900
UTF8_ECI = 26
ALPHA, LOWER, MIXED, PUNCT = range(4)
SUBMODE_NAMES = ("Alpha", "Lower", "Mixed", "Punct")
_MIXED_RAW = b"0123456789&\r\t,:#-.$/+%*=^"            # values 0–24, 26 = space
_PUNCT_RAW = b";<>@[\\]_`~!\r\t,:\n-.$/\"|*()?{}'"       # values 0–28
NUMERIC_MIN = 13                  # digit runs from this length go to Numeric compaction
TEXT_MIN = 5                      # text runs from this length leave Byte compaction


def _sub_table() -> list[dict[int, int]]:
    alpha = {c: c - 65 for c in range(65, 91)}
    alpha[32] = 26
    lower = {c: c - 97 for c in range(97, 123)}
    lower[32] = 26
    mixed = {c: i for i, c in enumerate(_MIXED_RAW)}
    mixed[32] = 26
    punct = {c: i for i, c in enumerate(_PUNCT_RAW)}
    return [alpha, lower, mixed, punct]


SUBMODES = _sub_table()
# latch sequences between submodes (values 27 LL / 28 ML or AL / 25 PL / 29 AL from Punct)
_LATCH = {
    (ALPHA, LOWER): (27,), (ALPHA, MIXED): (28,), (ALPHA, PUNCT): (28, 25),
    (LOWER, ALPHA): (28, 28), (LOWER, MIXED): (28,), (LOWER, PUNCT): (28, 25),
    (MIXED, ALPHA): (28,), (MIXED, LOWER): (27,), (MIXED, PUNCT): (25,),
    (PUNCT, ALPHA): (29,), (PUNCT, LOWER): (29, 27), (PUNCT, MIXED): (29, 28),
}


def is_text(b: int) -> bool:
    return b in (9, 10, 13) or 32 <= b <= 126


def text_values(data: bytes, submode: int = ALPHA) -> tuple[list[int], int]:
    """Shortest sequence of base-30 values for text bytes, starting in ``submode``.

    Returns (values, submode at the end). Uses latches and the shifts PS (one
    Punct character from Alpha/Lower/Mixed) and AS (one capital in Lower).
    """
    inf = float("inf")
    n = len(data)
    cost = [[inf] * 4 for _ in range(n + 1)]
    back: list[list[tuple | None]] = [[None] * 4 for _ in range(n + 1)]
    cost[0][submode] = 0
    for i, c in enumerate(data):
        for s in range(4):
            base = cost[i][s]
            if base == inf:
                continue
            for t in range(4):
                if c not in SUBMODES[t]:
                    continue
                seq = (SUBMODES[t][c],) if t == s else _LATCH[(s, t)] + (SUBMODES[t][c],)
                if base + len(seq) < cost[i + 1][t]:
                    cost[i + 1][t] = base + len(seq)
                    back[i + 1][t] = (s, seq)
            shift = None
            if s != PUNCT and c in SUBMODES[PUNCT] and c not in SUBMODES[s]:
                shift = (29, SUBMODES[PUNCT][c])
            elif s == LOWER and c in SUBMODES[ALPHA] and c != 32:
                shift = (27, SUBMODES[ALPHA][c])
            if shift and base + 2 < cost[i + 1][s]:
                cost[i + 1][s] = base + 2
                back[i + 1][s] = (s, shift)
    end = min(range(4), key=lambda s: cost[n][s])
    out: list[tuple] = []
    s = end
    for i in range(n, 0, -1):
        prev, seq = back[i][s]
        out.append(seq)
        s = prev
    return [v for seq in reversed(out) for v in seq], end


def _pack_text(values: list[int], submode: int) -> tuple[list[int], int]:
    """Two values per codeword; an odd count is padded with 29 (PS, or AL in Punct)."""
    values = list(values)
    if len(values) % 2:
        values.append(29)
        if submode == PUNCT:
            submode = ALPHA
    return [30 * values[i] + values[i + 1] for i in range(0, len(values), 2)], submode


def _base900(value: int, n: int) -> list[int]:
    out = []
    for _ in range(n):
        value, r = divmod(value, 900)
        out.append(r)
    return out[::-1]


def numeric_codewords(digits: bytes) -> list[int]:
    """Numeric compaction: groups of up to 44 digits, value of "1" + digits in base 900."""
    out = []
    for i in range(0, len(digits), 44):
        group = digits[i:i + 44]
        value = int(b"1" + group)
        out += _base900(value, len(group) // 3 + 1)
    return out


def byte_codewords(data: bytes) -> list[int]:
    """Byte compaction body: 6 bytes → 5 codewords, rest one codeword per byte."""
    out = []
    full = len(data) - len(data) % 6
    for i in range(0, full, 6):
        out += _base900(int.from_bytes(data[i:i + 6], "big"), 5)
    out += list(data[full:])
    return out


def _digit_run(data: bytes, p: int) -> int:
    e = p
    while e < len(data) and 48 <= data[e] <= 57:
        e += 1
    return e - p


def _text_run(data: bytes, p: int) -> int:
    e = p
    while e < len(data) and is_text(data[e]):
        if _digit_run(data, e) >= NUMERIC_MIN:
            break
        e += 1
    return e - p


def _byte_run(data: bytes, p: int) -> int:
    e = p
    while e < len(data):
        if _digit_run(data, e) >= NUMERIC_MIN or _text_run(data, e) >= TEXT_MIN:
            break
        e += 1
    return max(1, e - p)


def segments(data: bytes) -> list[tuple[str, bytes]]:
    """(mode, bytes) runs: "numeric", "text" or "byte" (see module doc)."""
    out: list[tuple[str, bytes]] = []
    mode, p = "text", 0
    while p < len(data):
        d = _digit_run(data, p)
        if d >= NUMERIC_MIN:
            n, mode = d, "numeric"
        else:
            t = _text_run(data, p)
            if t and (mode == "text" or t >= TEXT_MIN):
                n, mode = t, "text"
            else:
                n = _byte_run(data, p)
                mode = "byte"
        if out and out[-1][0] == mode:
            out[-1] = (mode, out[-1][1] + data[p:p + n])
        else:
            out.append((mode, data[p:p + n]))
        p += n
    return out


def text_bytes(text: str) -> tuple[bytes, bool]:
    """(bytes, needs ECI 26): ASCII as is, anything else as UTF-8."""
    try:
        return text.encode("ascii"), False
    except UnicodeEncodeError:
        return text.encode("utf-8"), True


def encode_data(text: str) -> list[int]:
    """Data codewords of ``text`` (without the symbol length descriptor and pads)."""
    if not text:
        raise ValueError("Kein Text für den PDF417-Code")
    data, eci = text_bytes(text)
    out = [ECI_CHARSET, UTF8_ECI] if eci else []
    mode, sub = "text", ALPHA                 # a symbol starts in Text compaction, Alpha
    for kind, chunk in segments(data):
        if kind == "text":
            if mode != "text":
                out.append(LATCH_TEXT)
                sub = ALPHA
            values, sub = text_values(chunk, sub)
            words, sub = _pack_text(values, sub)
            out += words
            mode = "text"
        elif kind == "numeric":
            out += [LATCH_NUMERIC] + numeric_codewords(chunk)
            mode = "numeric"
        elif mode == "text" and len(chunk) == 1:
            out += [SHIFT_BYTE, chunk[0]]       # stays in Text compaction, same submode
        else:
            out += [LATCH_BYTE6 if len(chunk) % 6 == 0 else LATCH_BYTE] + byte_codewords(chunk)
            mode = "byte"
    return out


# --- Reed-Solomon over GF(929) ------------------------------------------------------------

GF = 929


def ecc_count(level: int) -> int:
    return 2 << int(level)


@lru_cache(maxsize=None)
def generator(k: int) -> tuple[int, ...]:
    """Coefficients (highest degree first) of ∏ (x − 3^j), j = 1…k, mod 929."""
    g = [1]
    a = 1
    for _ in range(k):
        a = a * 3 % GF
        g = [(c - a * p) % GF for c, p in zip(g + [0], [0] + g)]
    return tuple(g)


def rs_ecc(data: list[int], level: int) -> list[int]:
    """Check codewords for ``data``: −(data · x^k mod g) so that 3^1…3^k are roots."""
    k = ecc_count(level)
    g = generator(k)
    msg = list(data) + [0] * k
    for i in range(len(data)):
        c = msg[i]
        if c:
            for j in range(1, k + 1):
                msg[i + j] = (msg[i + j] - c * g[j]) % GF
    return [(-r) % GF for r in msg[-k:]]


def recommended_level(data_words: int) -> int:
    """ISO/IEC 15438 recommendation for the number of data codewords (incl. length)."""
    for limit, level in ((40, 2), (160, 3), (320, 4), (863, 5)):
        if data_words <= limit:
            return level
    return 5


# --- symbol --------------------------------------------------------------------------

def _rows_for(n: int, columns: int) -> int:
    return max(ROWS_RANGE[0], -(-n // columns))


def symbol_width(columns: int, compact: bool = False) -> int:
    """Modules per row: start 17 + left indicator 17 + 17 per column (+ right 17) + stop."""
    return 17 * columns + (35 if compact else 69)


def choose_layout(source: int, level: int, columns: int = AUTO, compact: bool = False,
                  row_height: float = DEFAULT_ROW_HEIGHT) -> tuple[int, int]:
    """(columns, rows) for ``source`` data codewords (without length) and ``level``.

    ``columns`` 0: the layout whose width / height is closest to
    :data:`PREFERRED_RATIO` (ties: fewer codewords); otherwise that column count.
    Raises ``ValueError`` if nothing fits.
    """
    need = source + 1 + ecc_count(level)
    if need > MAX_CODEWORDS:
        raise ValueError("Text zu lang für einen PDF417-Code (höchstens 928 Codewörter) – "
                         "Text kürzen oder Fehlerkorrektur senken")
    if columns:
        r = _rows_for(need, columns)
        if r > ROWS_RANGE[1]:
            raise ValueError(f"Mit {columns} Spalte{'n' if columns > 1 else ''} wären es {r} Zeilen "
                             f"(höchstens {ROWS_RANGE[1]}) – mehr Spalten wählen")
        if columns * r > MAX_CODEWORDS:
            raise ValueError(f"{columns} × {r} = {columns * r} Codewörter sind zu viele "
                             f"(höchstens {MAX_CODEWORDS}) – andere Spaltenzahl wählen")
        return columns, r
    best = None
    for c in range(COLUMNS_RANGE[0], COLUMNS_RANGE[1] + 1):
        r = _rows_for(need, c)
        if r > ROWS_RANGE[1] or c * r > MAX_CODEWORDS:
            continue
        ratio = symbol_width(c, compact) / (r * row_height)
        key = (abs(math.log(ratio / PREFERRED_RATIO)), c * r)
        if best is None or key < best[0]:
            best = (key, c, r)
    if best is None:
        raise ValueError("Text zu lang für einen PDF417-Code – Text kürzen oder "
                         "Fehlerkorrektur senken")
    return best[1], best[2]


@dataclass(frozen=True)
class Pdf417Code:
    """Encoded symbol; ``modules[row][x]`` True = bar, one entry per codeword row."""

    columns: int
    rows: int
    ecc_level: int
    data_words: int               # incl. length descriptor and pads
    source_words: int             # high-level codewords
    compact: bool
    codewords: tuple[int, ...]
    modules: tuple[tuple[bool, ...], ...]
    recommended: int = 2          # ISO level for this data length

    @property
    def width(self) -> int:
        return symbol_width(self.columns, self.compact)

    @property
    def ecc_words(self) -> int:
        return ecc_count(self.ecc_level)

    @property
    def pad_words(self) -> int:
        return self.data_words - 1 - self.source_words

    def dark(self, x: int, row: int) -> bool:
        return 0 <= row < self.rows and 0 <= x < self.width and self.modules[row][x]

    def runs(self, invert: bool = False) -> list[tuple[int, int, int]]:
        """Horizontal runs (row, start, end excl.) of the modules to laser (no quiet zone)."""
        out = []
        for y, row in enumerate(self.modules):
            x = 0
            while x < self.width:
                if row[x] == invert:
                    x += 1
                    continue
                e = x
                while e < self.width and row[e] != invert:
                    e += 1
                out.append((y, x, e))
                x = e
        return out


def _bits(p: int, length: int) -> list[bool]:
    return [bool((p >> (length - 1 - k)) & 1) for k in range(length)]


def row_indicators(row: int, rows: int, columns: int, level: int) -> tuple[int, int]:
    """(left, right) row indicator codewords of ``row`` (ISO/IEC 15438 5.3.4)."""
    base = 30 * (row // 3)
    r_part, c_part, e_part = (rows - 1) // 3, columns - 1, 3 * level + (rows - 1) % 3
    cluster = row % 3
    if cluster == 0:
        return base + r_part, base + c_part
    if cluster == 1:
        return base + e_part, base + r_part
    return base + c_part, base + e_part


def build(columns: int, rows: int, level: int, codewords: list[int],
          compact: bool = False) -> tuple[tuple[bool, ...], ...]:
    """Module rows for the complete codeword sequence (data + check codewords)."""
    if len(codewords) != columns * rows:
        raise ValueError("Codewortzahl passt nicht zur Symbolgröße")
    out = []
    for y in range(rows):
        cluster = y % 3
        left, right = row_indicators(y, rows, columns, level)
        row = _bits(START_PATTERN, 17) + _bits(pattern(cluster, left), 17)
        for cw in codewords[y * columns:(y + 1) * columns]:
            row += _bits(pattern(cluster, cw), 17)
        if compact:
            row.append(True)
        else:
            row += _bits(pattern(cluster, right), 17) + _bits(STOP_PATTERN, 18)
        out.append(tuple(row))
    return tuple(out)


def encode(text: str, columns: int = AUTO, ecc_level: int = AUTO_ECC, compact: bool = False,
           row_height: float = DEFAULT_ROW_HEIGHT) -> Pdf417Code:
    """Encode ``text``; ``columns`` 0 = automatic, ``ecc_level`` −1 = ISO recommendation."""
    source = encode_data(text)
    rec = recommended_level(len(source) + 1)
    if ecc_level == AUTO_ECC:
        level = rec
        while level > 2 and len(source) + 1 + ecc_count(level) > MAX_CODEWORDS:
            level -= 1
    else:
        level = int(ecc_level)
        if level not in ECC_LEVELS:
            raise ValueError(f"Fehlerkorrektur-Stufe {ecc_level} gibt es nicht (0–8)")
    c, r = choose_layout(len(source), level, columns, compact, row_height)
    k = ecc_count(level)
    n_data = c * r - k
    data = [n_data] + source + [PAD] * (n_data - 1 - len(source))
    words = data + rs_ecc(data, level)
    return Pdf417Code(c, r, level, n_data, len(source), bool(compact), tuple(words),
                      build(c, r, level, words, compact), rec)


# --- Vector output ------------------------------------------------------------------

def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


@dataclass(frozen=True)
class Pdf417Spec:
    text: str = "LumaCut"
    columns: int = AUTO           # data columns, 0 = automatic
    ecc_level: int = AUTO_ECC     # 0–8, −1 = ISO recommendation
    width_mm: float = 40.0        # symbol width without quiet zone
    row_height: float = DEFAULT_ROW_HEIGHT   # row height in module widths
    quiet_zone: int = DEFAULT_QUIET          # module widths on all sides
    compact: bool = False         # Compact (truncated) PDF417
    invert: bool = False
    x: float = 0.0                # top left corner incl. quiet zone
    y: float = 0.0

    def normalized(self) -> "Pdf417Spec":
        try:
            cols = int(self.columns)
        except (TypeError, ValueError):
            cols = AUTO
        cols = AUTO if cols <= 0 else int(_clamp(cols, *COLUMNS_RANGE))
        try:
            lvl = int(self.ecc_level)
        except (TypeError, ValueError):
            lvl = AUTO_ECC
        lvl = AUTO_ECC if lvl < 0 else int(_clamp(lvl, 0, 8))
        return Pdf417Spec(text=str(self.text or ""), columns=cols, ecc_level=lvl,
                          width_mm=float(_clamp(float(self.width_mm), *WIDTH_RANGE)),
                          row_height=round(float(_clamp(float(self.row_height),
                                                        *ROW_HEIGHT_RANGE)), 3),
                          quiet_zone=int(_clamp(int(self.quiet_zone), *QUIET_RANGE)),
                          compact=bool(self.compact), invert=bool(self.invert),
                          x=float(self.x), y=float(self.y))

    def encode(self) -> Pdf417Code:
        s = self.normalized()
        return encode(s.text, s.columns, s.ecc_level, s.compact, s.row_height)

    def module_mm(self, code: Pdf417Code) -> float:
        return self.normalized().width_mm / code.width

    def height_mm(self, code: Pdf417Code) -> float:
        """Symbol height without quiet zone."""
        s = self.normalized()
        return self.module_mm(code) * s.row_height * code.rows

    def total(self, code: Pdf417Code) -> tuple[float, float]:
        s = self.normalized()
        m = self.module_mm(code)
        return s.width_mm + 2 * s.quiet_zone * m, self.height_mm(code) + 2 * s.quiet_zone * m


def regions(code: Pdf417Code, module_mm: float, row_height: float, quiet_zone: int = 0,
            invert: bool = False, origin: tuple[float, float] = (0.0, 0.0)):
    """Connected areas to laser as (outer ring, [holes]) in mm (Y down)."""
    from shapely.geometry import box
    from shapely.ops import unary_union

    q = max(0, int(quiet_zone))
    rects = [box(x0 + q, q + y * row_height, x1 + q, q + (y + 1) * row_height)
             for y, x0, x1 in code.runs(False)]
    merged = unary_union(rects)
    if invert:
        merged = box(0, 0, code.width + 2 * q, code.rows * row_height + 2 * q).difference(merged)
    polys = list(getattr(merged, "geoms", [merged]))
    ox, oy = origin
    out = []
    for p in polys:
        if p.is_empty:
            continue
        p = p.simplify(0)

        def ring(r):
            pts = [(ox + px * module_mm, oy + py * module_mm) for px, py in r.coords]
            return pts[:-1] if len(pts) > 1 and pts[0] == pts[-1] else pts
        out.append((ring(p.exterior), [ring(i) for i in p.interiors]))
    return out


def pdf417_shapes(spec: Pdf417Spec, layer_id: str, code: Pdf417Code | None = None) -> list[Shape]:
    """Symbol as grouped ``polygon`` objects (one area per object, holes as rings).

    Raises ``ValueError`` for empty/too long text, too small modules or when the
    symbol incl. quiet zone does not fit on the work area.
    """
    s = spec.normalized()
    code = code or s.encode()
    module = s.module_mm(code)
    if module < HARD_MIN_MODULE_MM - 1e-9:
        raise ValueError(f"Module {module:.2f} mm sind zu schmal (mindestens "
                         f"{HARD_MIN_MODULE_MM:.1f} mm) – Code breiter machen, Text kürzen, "
                         "weniger Spalten oder Fehlerkorrektur senken")
    tw, th = s.total(code)
    eps = 1e-6
    if (s.x < -eps or s.y < -eps or s.x + tw > WORK_WIDTH_MM + eps
            or s.y + th > WORK_HEIGHT_MM + eps):
        raise ValueError(
            f"PDF417-Code {tw:.1f} × {th:.1f} mm (inkl. Ruhezone) passt ab X {s.x:.1f} / "
            f"Y {s.y:.1f} nicht auf die Arbeitsfläche ({WORK_WIDTH_MM:.0f} × {WORK_HEIGHT_MM:.0f} mm)")
    group = new_id()
    out = []
    for outer, holes in regions(code, module, s.row_height, s.quiet_zone, s.invert, (s.x, s.y)):
        pts = list(outer)
        rings = []
        for h in holes:
            rings.append(len(pts))
            pts.extend(h)
        sh = Shape.from_points("polygon", pts, layer_id, rings=rings)
        sh.groups = (group,)
        out.append(sh)
    return out


def describe(code: Pdf417Code, width_mm: float, row_height: float = DEFAULT_ROW_HEIGHT) -> str:
    module = width_mm / code.width
    kind = ", kompakt" if code.compact else ""
    return (f"{code.columns} Spalte{'n' if code.columns > 1 else ''} × {code.rows} Zeilen "
            f"({code.width} Module breit{kind}), {code.data_words} Datenwörter, "
            f"Fehlerkorrektur Stufe {code.ecc_level} ({code.ecc_words} Prüfwörter), "
            f"Modul {module:.2f} × {module * row_height:.2f} mm, "
            f"Höhe {module * row_height * code.rows:.1f} mm")


__all__ = ["AUTO", "AUTO_ECC", "Pdf417Code", "Pdf417Spec", "build", "choose_layout", "describe",
           "encode", "encode_data", "numeric_codewords", "byte_codewords", "pdf417_shapes",
           "recommended_level", "rs_ecc", "segments", "text_values"]
