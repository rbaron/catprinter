
PRINT_WIDTH = 384


def to_unsigned_byte(val):
    '''Converts a byte in signed representation to unsigned. Assumes val is encoded in two's
    complement.'''
    return val if val >= 0 else val & 0xff


def bs(lst):
    '''This is an utility function that transforms a list of unsigned bytes (in two's complement)
    into an unsigned bytearray.

    The reason it exists is that in Java (where these commands were reverse engineered from), bytes
    are signed. Instead of manually converting them, let the computer do it for us, so it's easier
    to debug and extend it with new reverse engineered commands.
    '''
    return bytearray(map(to_unsigned_byte, lst))


CMD_GET_DEV_STATE = bs([
    81, 120, -93, 0, 1, 0, 0, 0, -1
])

CMD_SET_QUALITY_200_DPI = bs([81, 120, -92, 0, 1, 0, 50, -98, -1])

CMD_GET_DEV_INFO = bs([81, 120, -88, 0, 1, 0, 0, 0, -1])

CMD_LATTICE_START = bs([81, 120, -90, 0, 11, 0, -86, 85, 23,
                        56, 68, 95, 95, 95, 68, 56, 44, -95, -1])

CMD_LATTICE_END = bs([81, 120, -90, 0, 11, 0, -86, 85,
                     23, 0, 0, 0, 0, 0, 0, 0, 23, 17, -1])

CMD_SET_PAPER = bs([81, 120, -95, 0, 2, 0, 48, 0, -7, -1])

CMD_PRINT_IMG = bs([81, 120, -66, 0, 1, 0, 0, 0, -1])

CMD_PRINT_TEXT = bs([81, 120, -66, 0, 1, 0, 1, 7, -1])

CHECKSUM_TABLE = bs([
    0, 7, 14, 9, 28, 27, 18, 21, 56, 63, 54, 49, 36, 35, 42, 45, 112, 119, 126, 121,
    108, 107, 98, 101, 72, 79, 70, 65, 84, 83, 90, 93, -32, -25, -18, -23, -4, -5,
    -14, -11, -40, -33, -42, -47, -60, -61, -54, -51, -112, -105, -98, -103, -116,
    -117, -126, -123, -88, -81, -90, -95, -76, -77, -70, -67, -57, -64, -55, -50,
    -37, -36, -43, -46, -1, -8, -15, -10, -29, -28, -19, -22, -73, -80, -71, -66,
    -85, -84, -91, -94, -113, -120, -127, -122, -109, -108, -99, -102, 39, 32, 41,
    46, 59, 60, 53, 50, 31, 24, 17, 22, 3, 4, 13, 10, 87, 80, 89, 94, 75, 76, 69, 66,
    111, 104, 97, 102, 115, 116, 125, 122, -119, -114, -121, -128, -107, -110, -101,
    -100, -79, -74, -65, -72, -83, -86, -93, -92, -7, -2, -9, -16, -27, -30, -21, -20,
    -63, -58, -49, -56, -35, -38, -45, -44, 105, 110, 103, 96, 117, 114, 123, 124, 81,
    86, 95, 88, 77, 74, 67, 68, 25, 30, 23, 16, 5, 2, 11, 12, 33, 38, 47, 40, 61, 58,
    51, 52, 78, 73, 64, 71, 82, 85, 92, 91, 118, 113, 120, 127, 106, 109, 100, 99, 62,
    57, 48, 55, 34, 37, 44, 43, 6, 1, 8, 15, 26, 29, 20, 19, -82, -87, -96, -89, -78,
    -75, -68, -69, -106, -111, -104, -97, -118, -115, -124, -125, -34, -39, -48, -41,
    -62, -59, -52, -53, -26, -31, -24, -17, -6, -3, -12, -13,
])


def chk_sum(b_arr, i, i2):
    b2 = 0
    for i3 in range(i, i + i2):
        b2 = CHECKSUM_TABLE[(b2 ^ b_arr[i3]) & 0xff]
    return b2


def cmd_feed_paper(how_much):
    b_arr = bs([
        81,
        120,
        -67,
        0,
        1,
        0,
        how_much & 0xff,
        0,
        0xff,
    ])
    b_arr[7] = chk_sum(b_arr, 6, 1)
    return bs(b_arr)


def cmd_set_energy(val):
    b_arr = bs([
        81,
        120,
        -81,
        0,
        2,
        0,
        (val >> 8) & 0xff,
        val & 0xff,
        0,
        0xff,
    ])
    b_arr[8] = chk_sum(b_arr, 6, 2)
    return bs(b_arr)


def cmd_apply_energy():
    b_arr = bs(
        [
            81,
            120,
            -66,
            0,
            1,
            0,
            1,
            0,
            0xff,
        ]
    )
    b_arr[7] = chk_sum(b_arr, 6, 1)
    return bs(b_arr)


def encode_run_length_repetition(n, val):
    res = []
    while n > 0x7f:
        res.append(0x7f | (val << 7))
        n -= 0x7f
    if n > 0:
        res.append((val << 7) | n)
    return res


def run_length_encode(img_row):
    res = []
    count = 0
    last_val = -1
    for val in img_row:
        if val == last_val:
            count += 1
        else:
            res.extend(encode_run_length_repetition(count, last_val))
            count = 1
        last_val = val
    if count > 0:
        res.extend(encode_run_length_repetition(count, last_val))
    return res


def byte_encode(img_row):
    def bit_encode(chunk_start, bit_index):
        return 1 << bit_index if img_row[chunk_start + bit_index] else 0

    res = []
    for chunk_start in range(0, len(img_row), 8):
        byte = 0
        for bit_index in range(8):
            byte |= bit_encode(chunk_start, bit_index)
        res.append(byte)
    return res


def cmd_print_row(img_row):
    # Try to use run-length compression on the image data.
    encoded_img = run_length_encode(img_row)

    # If the resulting compression takes more than PRINT_WIDTH // 8, it means
    # it's not worth it. So we fallback to a simpler, fixed-length encoding.
    if len(encoded_img) > PRINT_WIDTH // 8:
        encoded_img = byte_encode(img_row)
        b_arr = bs([
            81,
            120,
            -94,
            0,
            len(encoded_img),
            0] + encoded_img + [0, 0xff])
        b_arr[-2] = chk_sum(b_arr, 6, len(encoded_img))
        return b_arr

    # Build the run-length encoded image command.
    b_arr = bs([
        81,
        120,
        -65,
        0,
        len(encoded_img),
        0] + encoded_img + [0, 0xff])
    b_arr[-2] = chk_sum(b_arr, 6, len(encoded_img))
    return b_arr


def cmds_print_img(img, energy: int = 0xffff):
    data = \
        CMD_GET_DEV_STATE + \
        CMD_SET_QUALITY_200_DPI + \
        cmd_set_energy(energy) + \
        cmd_apply_energy() + \
        CMD_LATTICE_START
    for row in img:
        data += cmd_print_row(row)
    data += \
        cmd_feed_paper(25) + \
        CMD_SET_PAPER + \
        CMD_SET_PAPER + \
        CMD_SET_PAPER + \
        CMD_LATTICE_END + \
        CMD_GET_DEV_STATE
    return data
