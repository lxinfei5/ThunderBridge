#!/usr/bin/env python3
"""Conway's Game of Life -- UltraCode-Shim demo (intentionally unfinished).

It runs, but it's a little buggy and pretty boring:
  - the simulation has a subtle bug (a stable 2x2 "block" won't stay stable,
    and a "blinker" won't oscillate cleanly),
  - it just prints 5 frames and quits -- no animation, no color, no patterns.

That's on purpose. See PROMPT.md for the demo task to hand to UltraCode.

    python3 life.py
"""
import random

WIDTH, HEIGHT = 40, 20


def new_grid(random_fill=True):
    return [[1 if (random_fill and random.random() < 0.25) else 0
             for _ in range(WIDTH)] for _ in range(HEIGHT)]


def count_neighbors(grid, x, y):
    # BUG: this sums a 3x3 block, so it counts the cell ITSELF as one of its
    # own neighbors. The Game of Life rules need the 8 surrounding cells only.
    total = 0
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            ny, nx = (y + dy) % HEIGHT, (x + dx) % WIDTH
            total += grid[ny][nx]
    return total


def step(grid):
    nxt = new_grid(random_fill=False)
    for y in range(HEIGHT):
        for x in range(WIDTH):
            n = count_neighbors(grid, x, y)
            alive = grid[y][x]
            nxt[y][x] = 1 if (n == 3 or (alive and n == 2)) else 0
    return nxt


def render(grid):
    for row in grid:
        print("".join("#" if cell else "." for cell in row))


def main():
    grid = new_grid()
    for _ in range(5):
        render(grid)
        print("-" * WIDTH)
        grid = step(grid)


if __name__ == "__main__":
    main()
