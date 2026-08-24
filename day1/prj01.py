############################載入套件############################
from pdb import run
from tkinter import W

from annotated_types import T
import pygame

############################遊戲機本設定############################
WIDTH = 800
HEIGHT = 600
FPS = 60
BACKGROUND = (255, 255, 255)
############################初始化設定############################
pygame.init()
############################遊戲視窗設定############################
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("python x sdd")
clock = pygame.time.Clock()
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
    # 更新畫面
    pygame.display.update()
############################遊戲結束設定############################
pygame.quit()
