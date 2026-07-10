#!/usr/bin/python3
# coding=utf-8
"""Generate a printable AprilGrid calibration board (PNG + PDF) and its board.yaml.

Print the PDF at 100% / "actual size" (no "fit to page" / "shrink to fit"),
otherwise the physical tag size will not match tag_size_mm and the
calibrator's metric scale will be wrong. Mount the printout on a flat, rigid
surface before capturing calibration images.
"""

import argparse

import cv2
import numpy as np
from PIL import Image

from aprilgrid_board import Board, save_board_yaml


def build_canvas(board: Board, margin_mm: float, dpi: float) -> np.ndarray:
    px_per_mm = dpi / 25.4
    tag_size_mm = board.tag_size_m * 1000.0
    pitch_mm = board.pitch_m * 1000.0

    board_w_mm = (board.cols - 1) * pitch_mm + tag_size_mm
    board_h_mm = (board.rows - 1) * pitch_mm + tag_size_mm
    canvas_w_mm = board_w_mm + 2 * margin_mm
    canvas_h_mm = board_h_mm + 2 * margin_mm

    canvas_w_px = int(round(canvas_w_mm * px_per_mm))
    canvas_h_px = int(round(canvas_h_mm * px_per_mm))
    canvas = np.full((canvas_h_px, canvas_w_px), 255, dtype=np.uint8)

    dictionary = board.dictionary()
    tag_size_px = int(round(tag_size_mm * px_per_mm))
    margin_px = margin_mm * px_per_mm
    pitch_px = pitch_mm * px_per_mm

    for row in range(board.rows):
        for col in range(board.cols):
            tag_id = board.start_id + row * board.cols + col
            marker = cv2.aruco.generateImageMarker(dictionary, tag_id, tag_size_px)
            x0 = int(round(margin_px + col * pitch_px))
            y0 = int(round(margin_px + row * pitch_px))
            canvas[y0 : y0 + tag_size_px, x0 : x0 + tag_size_px] = marker

    return canvas


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a printable AprilGrid fisheye calibration board",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--rows", type=int, default=6, help="Number of tag rows")
    parser.add_argument("--cols", type=int, default=6, help="Number of tag columns")
    parser.add_argument(
        "--tag-size-mm",
        type=float,
        default=50.0,
        help="Physical size of one printed tag, edge to edge (mm)",
    )
    parser.add_argument(
        "--tag-spacing",
        type=float,
        default=0.3,
        help="Gap between tags, as a fraction of tag-size-mm",
    )
    parser.add_argument("--margin-mm", type=float, default=15.0, help="White border around the grid (mm)")
    parser.add_argument("--dpi", type=float, default=300.0, help="Print resolution")
    parser.add_argument("--start-id", type=int, default=0, help="First AprilTag id used")
    parser.add_argument("--family", default="DICT_APRILTAG_36h11", help="cv2.aruco dictionary constant name")
    parser.add_argument("--output", default="aprilgrid", help="Output basename (no extension)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    board = Board(
        family=args.family,
        rows=args.rows,
        cols=args.cols,
        tag_size_m=args.tag_size_mm / 1000.0,
        tag_spacing=args.tag_spacing,
        start_id=args.start_id,
    )

    dict_size = board.dictionary().bytesList.shape[0]
    if board.start_id + board.num_tags > dict_size:
        raise SystemExit(
            f"{board.family} only has {dict_size} tags; "
            f"start_id={board.start_id} + rows*cols={board.num_tags} exceeds it"
        )

    canvas = build_canvas(board, args.margin_mm, args.dpi)

    png_path = f"{args.output}.png"
    pdf_path = f"{args.output}.pdf"
    yaml_path = f"{args.output}.board.yaml"

    cv2.imwrite(png_path, canvas)
    Image.fromarray(canvas).convert("L").save(pdf_path, "PDF", resolution=args.dpi)
    save_board_yaml(yaml_path, board)

    board_w_mm = (board.cols - 1) * board.pitch_m * 1000.0 + args.tag_size_mm
    board_h_mm = (board.rows - 1) * board.pitch_m * 1000.0 + args.tag_size_mm
    print(f"AprilGrid {board.rows}x{board.cols}, tag_size={args.tag_size_mm:.1f}mm, "
          f"spacing={args.tag_spacing:.2f}x")
    print(f"Tag ids: {board.start_id}..{board.start_id + board.num_tags - 1}")
    print(f"Printable area: {board_w_mm:.1f} x {board_h_mm:.1f} mm "
          f"(+{args.margin_mm:.0f}mm margin each side)")
    print(f"Wrote {png_path}, {pdf_path}, {yaml_path}")
    print("Print the PDF at 100% / actual size (not 'fit to page'), then mount it flat and rigid.")


if __name__ == "__main__":
    main()
