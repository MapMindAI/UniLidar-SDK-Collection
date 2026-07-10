#!/usr/bin/python3
# coding=utf-8
"""AprilGrid calibration board geometry, shared by the generator and calibrator."""

from dataclasses import dataclass

import cv2
import yaml


@dataclass
class Board:
    family: str
    rows: int
    cols: int
    tag_size_m: float
    tag_spacing: float
    start_id: int

    @property
    def pitch_m(self) -> float:
        return self.tag_size_m * (1.0 + self.tag_spacing)

    @property
    def num_tags(self) -> int:
        return self.rows * self.cols

    def dictionary(self):
        dict_const = getattr(cv2.aruco, self.family)
        return cv2.aruco.getPredefinedDictionary(dict_const)

    def tag_object_points(self, row: int, col: int):
        """Corners in board-frame coords, order: top-left, top-right, bottom-right, bottom-left.

        This must match the corner order cv2.aruco returns for a marker printed
        with no extra rotation relative to the board frame (which is how
        generate_aprilgrid.py pastes each tag).
        """
        x0 = col * self.pitch_m
        y0 = row * self.pitch_m
        s = self.tag_size_m
        return [
            (x0, y0, 0.0),
            (x0 + s, y0, 0.0),
            (x0 + s, y0 + s, 0.0),
            (x0, y0 + s, 0.0),
        ]

    def object_points_by_id(self) -> dict:
        """Map AprilTag id -> 4x3 object points for every tag on this board."""
        points = {}
        for row in range(self.rows):
            for col in range(self.cols):
                tag_id = self.start_id + row * self.cols + col
                points[tag_id] = self.tag_object_points(row, col)
        return points


def save_board_yaml(path: str, board: Board) -> None:
    with open(path, "w") as f:
        yaml.safe_dump(
            {
                "family": board.family,
                "rows": board.rows,
                "cols": board.cols,
                "tag_size_m": board.tag_size_m,
                "tag_spacing": board.tag_spacing,
                "start_id": board.start_id,
            },
            f,
            sort_keys=False,
        )


def load_board_yaml(path: str) -> Board:
    with open(path) as f:
        data = yaml.safe_load(f)
    return Board(
        family=data["family"],
        rows=int(data["rows"]),
        cols=int(data["cols"]),
        tag_size_m=float(data["tag_size_m"]),
        tag_spacing=float(data["tag_spacing"]),
        start_id=int(data["start_id"]),
    )
