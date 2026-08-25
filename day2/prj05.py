"""Day 1 p32–37：加入牆、底板與磚塊碰撞。"""

######################載入套件######################

import pygame

######################遊戲基本設定######################

WIDTH = 800
HEIGHT = 600
FPS = 60

BACKGROUND = (15, 23, 42)
PADDLE_COLOR = (241, 245, 249)
BALL_COLOR = (255, 255, 255)
BRICK_COLORS = [
    (244, 114, 182),
    (251, 146, 60),
    (250, 204, 21),
    (74, 222, 128),
    (56, 189, 248),
]


######################物件類別######################


class Brick:
    def __init__(self, x, y, width, height, color):
        self.rect = pygame.Rect(x, y, width, height)
        self.color = color
        self.alive = True

    def draw(self, surface):
        if self.alive:
            pygame.draw.rect(surface, self.color, self.rect, border_radius=5)


class Paddle:
    def __init__(self):
        self.rect = pygame.Rect(0, 0, 120, 16)
        self.rect.midbottom = (WIDTH // 2, HEIGHT - 34)
        self.speed = 8

    def update(self, keys):
        direction = 0
        if keys[pygame.K_LEFT] or keys[pygame.K_a]:
            direction -= 1
        if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
            direction += 1

        self.rect.x += direction * self.speed
        self.rect.x = max(0, min(self.rect.x, WIDTH - self.rect.width))

    def draw(self, surface):
        pygame.draw.rect(surface, PADDLE_COLOR, self.rect, border_radius=8)


class Ball:
    """Ball 負責自己的位置、速度、發射與牆面反彈。"""

    def __init__(self, paddle):
        self.radius = 9
        self.position = pygame.Vector2(0, 0)
        self.velocity = pygame.Vector2(5, -5)
        self.rect = pygame.Rect(0, 0, self.radius * 2, self.radius * 2)
        self.launched = False
        self.reset(paddle)

    def reset(self, paddle):
        self.launched = False
        self.position.update(paddle.rect.centerx, paddle.rect.top - self.radius)
        self.velocity.update(5, -5)
        self.rect.center = (round(self.position.x), round(self.position.y))

    def launch(self):
        self.launched = True

    def update(self, paddle):
        if not self.launched:
            self.position.update(
                paddle.rect.centerx,
                paddle.rect.top - self.radius,
            )
        else:
            self.position += self.velocity

            if self.position.x - self.radius <= 0:
                self.position.x = self.radius
                self.velocity.x *= -1
            elif self.position.x + self.radius >= WIDTH:
                self.position.x = WIDTH - self.radius
                self.velocity.x *= -1

            if self.position.y - self.radius <= 0:
                self.position.y = self.radius
                self.velocity.y *= -1

            if self.position.y - self.radius > HEIGHT:
                self.reset(paddle)

        self.rect.center = (round(self.position.x), round(self.position.y))

    def draw(self, surface):
        pygame.draw.circle(surface, BALL_COLOR, self.rect.center, self.radius)


######################定義函式區######################


def create_bricks():
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
            x = start_x + column * (brick_width + gap)
            y = start_y + row * (brick_height + gap)
            color = BRICK_COLORS[row]
            bricks.append(Brick(x, y, brick_width, brick_height, color))

    return bricks


def bounce_from_rect(ball, target_rect):
    """找出重疊最少的一側，決定反轉水平或垂直速度。"""
    overlaps = {
        "left": ball.rect.right - target_rect.left,
        "right": target_rect.right - ball.rect.left,
        "top": ball.rect.bottom - target_rect.top,
        "bottom": target_rect.bottom - ball.rect.top,
    }
    collision_side = min(overlaps, key=overlaps.get)

    if collision_side in ("left", "right"):
        ball.velocity.x *= -1
    else:
        ball.velocity.y *= -1


def handle_collisions(ball, paddle, bricks):
    # 碰撞處理固定走三步：找到、改狀態、改方向。
    # 檢查底板碰撞
    if ball.velocity.y > 0 and ball.rect.colliderect(paddle.rect):
        ball.rect.bottom = paddle.rect.top
        ball.position.y = ball.rect.centery
        ball.velocity.y = -abs(ball.velocity.y)

        offset = (ball.rect.centerx - paddle.rect.centerx) / (paddle.rect.width / 2)
        ball.velocity.x = 6 * offset

    # 檢查磚塊碰撞
    for brick in bricks:
        if brick.alive and ball.rect.colliderect(brick.rect):
            brick.alive = False
            bounce_from_rect(ball, brick.rect)
            break


######################初始化設定######################

pygame.init()

######################遊戲視窗設定######################

screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Checkpoint 05：碰撞")
clock = pygame.time.Clock()

######################磚塊######################

bricks = create_bricks()

######################底板設定######################

paddle = Paddle()

######################球設定######################

ball = Ball(paddle)

######################主程式######################

running = True
while running:
    # 設定 FPS
    clock.tick(FPS)

    # 偵測關閉與鍵盤事件
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                running = False
            elif event.key == pygame.K_SPACE:
                ball.launch()

    # 取得鍵盤狀態並更新遊戲物件
    keys = pygame.key.get_pressed()
    paddle.update(keys)
    ball.update(paddle)
    handle_collisions(ball, paddle, bricks)

    # 清除畫面
    screen.fill(BACKGROUND)

    # 顯示磚塊、底板與球
    for brick in bricks:
        brick.draw(screen)
    paddle.draw(screen)
    ball.draw(screen)

    # 更新畫面
    pygame.display.flip()

######################遊戲結束設定######################

pygame.quit()
