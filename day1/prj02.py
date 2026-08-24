############################載入套件############################
from pdb import run
import re
from tkinter import W
from turtle import st

from annotated_types import T
import pygame

############################遊戲機本設定############################
WIDTH = 800
HEIGHT = 600
FPS = 60
BACKGROUND = (15, 23, 42)
BRICK_COLORS = [
    (244, 144, 182),
    (251, 146, 60),
    (250, 204, 21),
    (74, 222, 128),
    (56, 189, 248),
]
############################初始化設定############################
pygame.init()
############################遊戲視窗設定############################
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("python x sdd")
clock = pygame.time.Clock()


############################定義函式區############################
def create_bricks():
    """用同一份Brick類別建立五列九欄磚塊"""
    bricks = []
    rows = 5
    columns = 9
    brick_width = 72
    brick_height = 24
    gap = 8
    start_x = 44
    start_y = 70
    for row in range(rows):
        for column in range(columns):
            x = start_x + (brick_width + gap) * column
            y = start_y + (brick_height + gap) * row
            color = BRICK_COLORS[row]
            bricks.append(Brick(x, y, brick_width, brick_height, color))
    return bricks


############################物件類別############################
class Brick:
    def __init__(self, x, y, width, height, color):
        self.rect = pygame.Rect(x, y, width, height)
        self.color = color
        self.alive = True

    def draw(self, surface):
        if self.alive:
            pygame.draw.rect(surface, self.color, self.rect, border_radius=5)


############################磚塊############################
bricks = create_bricks()
############################主程式############################
running = True
while running:
    # 設定FPS
    clock.tick(FPS)
    # 偵測關閉與鍵盤事件
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            running = False
    # 清除畫面
    screen.fill(BACKGROUND)
    # 顯示磚塊
    for brick in bricks:
        brick.draw(screen)
    # 更新畫面
    pygame.display.update()
############################遊戲結束設定############################
pygame.quit()
