import cv2


def read_img(filename, print_width):
    im = cv2.imread(filename, cv2.IMREAD_GRAYSCALE)
    height = im.shape[0]
    width = im.shape[1]
    factor = print_width / width
    resized = cv2.resize(im, (int(width * factor), int(height *
                         factor)), interpolation=cv2.INTER_AREA)

    # This also inverts the image.
    return resized < resized.mean()
