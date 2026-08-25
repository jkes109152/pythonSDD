"""Day 2：加入完整磚牆、特殊球、爆炸動畫與生命制度。"""

######################載入套件######################

import random

import pygame

######################遊戲基本設定######################

WIDTH = 800
HEIGHT = 600
FPS = 60

BACKGROUND = (15, 23, 42)
PADDLE_COLOR = (241, 245, 249)
BALL_COLOR = (255, 255, 255)
EXPLOSION_COLOR = (255, 80, 50)
PIERCING_COLOR = (180, 100, 255)
MULTIBALL_COLOR = (34, 211, 238)
LIFE_COLOR = (248, 113, 113)
WIDE_COLOR = (74, 222, 128)
HARD_2_COLOR = (148, 163, 184)
HARD_3_COLOR = (100, 116, 139)
BRICK_COLORS = [
    (244, 114, 182),
    (251, 146, 60),
    (250, 204, 21),
    (74, 222, 128),
    (56, 189, 248),
]


######################物件類別######################


class Brick:
    def __init__(self, x, y, width, height, color, brick_type, row, column):
        self.rect = pygame.Rect(x, y, width, height)
        self.color = color
        self.brick_type = brick_type
        self.row = row
        self.column = column
        self.alive = True
        self.health = 1
        self.max_health = 1

    def set_type(self, brick_type, color):
        """設定磚塊種類、顏色與需要撞擊的次數。"""
        self.brick_type = brick_type
        self.color = color

        if brick_type == "hard_2":
            self.health = 2
            self.max_health = 2
        elif brick_type == "hard_3":
            self.health = 3
            self.max_health = 3
        else:
            self.health = 1
            self.max_health = 1

    def draw(self, surface):
        if self.alive:
            pygame.draw.rect(surface, self.color, self.rect, border_radius=5)

            # 爆炸磚塊上畫一個小炸彈圖示。
            if self.brick_type == "explosion":
                icon_x = self.rect.centerx
                icon_y = self.rect.centery + 2
                pygame.draw.circle(surface, BACKGROUND, (icon_x, icon_y), 6)
                pygame.draw.line(
                    surface,
                    BACKGROUND,
                    (icon_x + 3, icon_y - 5),
                    (icon_x + 8, icon_y - 9),
                    2,
                )
                pygame.draw.circle(
                    surface,
                    (255, 230, 80),
                    (icon_x + 9, icon_y - 10),
                    2,
                )

            # 穿透磚塊上畫一個向下箭頭圖示。
            elif self.brick_type == "piercing":
                icon_x = self.rect.centerx
                icon_top = self.rect.top + 5
                icon_bottom = self.rect.bottom - 5
                pygame.draw.line(
                    surface,
                    BALL_COLOR,
                    (icon_x, icon_top),
                    (icon_x, icon_bottom),
                    3,
                )
                pygame.draw.line(
                    surface,
                    BALL_COLOR,
                    (icon_x, icon_bottom),
                    (icon_x - 5, icon_bottom - 6),
                    3,
                )
                pygame.draw.line(
                    surface,
                    BALL_COLOR,
                    (icon_x, icon_bottom),
                    (icon_x + 5, icon_bottom - 6),
                    3,
                )

            # 多球磚塊上畫三顆小球。
            elif self.brick_type == "multiball":
                pygame.draw.circle(
                    surface,
                    BALL_COLOR,
                    (self.rect.centerx, self.rect.centery - 4),
                    3,
                )
                pygame.draw.circle(
                    surface,
                    BALL_COLOR,
                    (self.rect.centerx - 6, self.rect.centery + 4),
                    3,
                )
                pygame.draw.circle(
                    surface,
                    BALL_COLOR,
                    (self.rect.centerx + 6, self.rect.centery + 4),
                    3,
                )

            # 加生命磚塊上畫加號。
            elif self.brick_type == "life":
                pygame.draw.line(
                    surface,
                    BALL_COLOR,
                    (self.rect.centerx - 7, self.rect.centery),
                    (self.rect.centerx + 7, self.rect.centery),
                    4,
                )
                pygame.draw.line(
                    surface,
                    BALL_COLOR,
                    (self.rect.centerx, self.rect.centery - 7),
                    (self.rect.centerx, self.rect.centery + 7),
                    4,
                )

            # 加長底板磚塊上畫一條長底板。
            elif self.brick_type == "wide":
                pygame.draw.line(
                    surface,
                    BALL_COLOR,
                    (self.rect.centerx - 15, self.rect.centery),
                    (self.rect.centerx + 15, self.rect.centery),
                    5,
                )
                pygame.draw.line(
                    surface,
                    BALL_COLOR,
                    (self.rect.centerx - 15, self.rect.centery - 5),
                    (self.rect.centerx - 15, self.rect.centery + 5),
                    2,
                )
                pygame.draw.line(
                    surface,
                    BALL_COLOR,
                    (self.rect.centerx + 15, self.rect.centery - 5),
                    (self.rect.centerx + 15, self.rect.centery + 5),
                    2,
                )

            # 硬磚上用直線顯示還剩幾次撞擊。
            elif self.brick_type == "hard_2" or self.brick_type == "hard_3":
                start_x = self.rect.centerx - (self.health - 1) * 4
                for number in range(self.health):
                    line_x = start_x + number * 8
                    pygame.draw.line(
                        surface,
                        BALL_COLOR,
                        (line_x, self.rect.centery - 6),
                        (line_x, self.rect.centery + 6),
                        3,
                    )


class Paddle:
    def __init__(self):
        self.rect = pygame.Rect(0, 0, 120, 16)
        self.rect.midbottom = (WIDTH // 2, HEIGHT - 34)
        self.speed = 8
        self.normal_width = 120
        self.wide_width = 180
        self.wide_frames = 0

    def make_wide(self):
        """把底板加長 600 幀，再次取得會重新計時。"""
        center_x = self.rect.centerx
        self.rect.width = self.wide_width
        self.rect.centerx = center_x
        self.rect.x = max(0, min(self.rect.x, WIDTH - self.rect.width))
        self.wide_frames = 600

    def update_power(self):
        """倒數加長底板的剩餘時間。"""
        if self.wide_frames > 0:
            self.wide_frames -= 1
            if self.wide_frames == 0:
                self.reset_size()

    def reset_size(self):
        """讓底板恢復原本寬度。"""
        center_x = self.rect.centerx
        self.rect.width = self.normal_width
        self.rect.centerx = center_x
        self.rect.x = max(0, min(self.rect.x, WIDTH - self.rect.width))

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
    """Ball 負責自己的位置、速度、發射與特殊球狀態。"""

    def __init__(self, paddle):
        self.radius = 9
        self.position = pygame.Vector2(0, 0)
        self.velocity = pygame.Vector2(5, -5)
        self.rect = pygame.Rect(0, 0, self.radius * 2, self.radius * 2)
        self.launched = False
        self.effect = "normal"
        self.effect_waiting = False
        self.explosion_hits = 0
        self.pierced_rows = []
        self.reset(paddle)

    def clear_effect(self):
        """清除特殊球效果，讓球恢復成普通球。"""
        self.effect = "normal"
        self.effect_waiting = False
        self.explosion_hits = 0
        self.pierced_rows = []

    def get_effect(self, effect):
        """取得效果後先變色，等碰到底板才啟動。"""
        self.effect = effect
        self.effect_waiting = True
        self.explosion_hits = 0
        self.pierced_rows = []

    def activate_effect(self):
        """球碰到底板時，啟動正在等待的特殊效果。"""
        if self.effect_waiting:
            self.effect_waiting = False
            if self.effect == "explosion":
                self.explosion_hits = 3
            elif self.effect == "piercing":
                self.pierced_rows = []

    def reset(self, paddle):
        self.launched = False
        self.position.update(paddle.rect.centerx, paddle.rect.top - self.radius)
        self.velocity.update(5, -5)
        self.rect.center = (round(self.position.x), round(self.position.y))
        self.clear_effect()

    def launch(self):
        self.launched = True

    def update(self, paddle):
        ball_lost = False

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

            # 球掉出畫面時通知主程式扣除生命。
            if self.position.y - self.radius > HEIGHT:
                ball_lost = True

        self.rect.center = (round(self.position.x), round(self.position.y))
        return ball_lost

    def draw(self, surface):
        color = BALL_COLOR
        if self.effect == "explosion":
            color = EXPLOSION_COLOR
        elif self.effect == "piercing":
            color = PIERCING_COLOR

        pygame.draw.circle(surface, color, self.rect.center, self.radius)


class Explosion:
    """用逐漸變大的圓圈顯示簡單的爆炸動畫。"""

    def __init__(self, x, y):
        self.center = (x, y)
        self.radius = 8
        self.max_radius = 100

    def update(self):
        # 每一幀增加 3，動畫大約半秒後結束。
        self.radius += 3
        return self.radius <= self.max_radius

    def draw(self, surface):
        # 外圈是橘色，內圈是黃色。
        pygame.draw.circle(
            surface,
            EXPLOSION_COLOR,
            self.center,
            self.radius,
            4,
        )
        if self.radius > 8:
            pygame.draw.circle(
                surface,
                (255, 230, 80),
                self.center,
                self.radius - 8,
                2,
            )


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
            # 每個格子都建立磚塊，所以每局固定有 45 塊。
            x = start_x + column * (brick_width + gap)
            y = start_y + row * (brick_height + gap)
            color_number = random.randint(0, len(BRICK_COLORS) - 1)
            color = BRICK_COLORS[color_number]
            bricks.append(
                Brick(
                    x,
                    y,
                    brick_width,
                    brick_height,
                    color,
                    "normal",
                    row,
                    column,
                )
            )

    # 每種特殊磚塊的種類、數量與顏色。
    brick_types = [
        "explosion",
        "piercing",
        "multiball",
        "life",
        "wide",
        "hard_2",
        "hard_3",
    ]
    brick_counts = [2, 2, 3, 3, 3, 6, 6]
    brick_type_colors = [
        EXPLOSION_COLOR,
        PIERCING_COLOR,
        MULTIBALL_COLOR,
        LIFE_COLOR,
        WIDE_COLOR,
        HARD_2_COLOR,
        HARD_3_COLOR,
    ]

    # 隨機選位置，只有普通磚塊才能被改成特殊磚塊。
    # 因此每一個特殊位置都不會重複。
    for type_number in range(len(brick_types)):
        placed_count = 0
        while placed_count < brick_counts[type_number]:
            number = random.randint(0, len(bricks) - 1)
            if bricks[number].brick_type == "normal":
                bricks[number].set_type(
                    brick_types[type_number],
                    brick_type_colors[type_number],
                )
                placed_count += 1

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


def get_brick_score(brick):
    """依照磚塊種類決定打碎後得到的分數。"""
    if brick.brick_type == "normal":
        return 10
    elif brick.brick_type == "hard_2":
        return 30
    elif brick.brick_type == "hard_3":
        return 50
    else:
        return 20


def explode_bricks(hit_brick, bricks, explosions):
    """清除九宮格磚塊，並回傳所有被打碎磚塊的分數。"""
    gained_score = 0
    for brick in bricks:
        row_distance = abs(brick.row - hit_brick.row)
        column_distance = abs(brick.column - hit_brick.column)
        if brick.alive and row_distance <= 1 and column_distance <= 1:
            gained_score += get_brick_score(brick)
            brick.alive = False
            brick.health = 0

    # 在撞中的磚塊中心加入一個爆炸動畫。
    explosions.append(Explosion(hit_brick.rect.centerx, hit_brick.rect.centery))
    return gained_score


def handle_collisions(ball, paddle, bricks, explosions):
    gained_score = 0
    power_type = ""

    # 碰撞處理固定走三步：找到、改狀態、改方向。
    # 檢查底板碰撞
    if ball.velocity.y > 0 and ball.rect.colliderect(paddle.rect):
        ball.rect.bottom = paddle.rect.top
        ball.position.y = ball.rect.centery
        ball.velocity.y = -abs(ball.velocity.y)

        offset = (ball.rect.centerx - paddle.rect.centerx) / (paddle.rect.width / 2)
        ball.velocity.x = 6 * offset

        # 特殊球一定要先碰到底板，才會正式啟動能力。
        ball.activate_effect()

    # 檢查磚塊碰撞
    for brick in bricks:
        if brick.alive and ball.rect.colliderect(brick.rect):
            hit_type = brick.brick_type
            brick_destroyed = False

            if ball.effect == "explosion" and not ball.effect_waiting:
                gained_score = explode_bricks(brick, bricks, explosions)
                brick_destroyed = True
                bounce_from_rect(ball, brick.rect)
                ball.explosion_hits -= 1
                if ball.explosion_hits == 0:
                    ball.clear_effect()

            elif ball.effect == "piercing" and not ball.effect_waiting:
                brick.alive = False
                brick.health = 0
                brick_destroyed = True
                gained_score = get_brick_score(brick)

                # 同一排只記錄一次，穿過三個不同排才會結束。
                if brick.row not in ball.pierced_rows:
                    ball.pierced_rows.append(brick.row)
                if len(ball.pierced_rows) == 3:
                    ball.clear_effect()

            else:
                # 普通球每次只減少硬磚一點耐久度。
                brick.health -= 1
                bounce_from_rect(ball, brick.rect)
                if brick.health == 0:
                    brick.alive = False
                    brick_destroyed = True
                    gained_score = get_brick_score(brick)

            if brick_destroyed:
                # 撞中的特殊磚塊只負責給能力，不會被新能力影響。
                if hit_type == "explosion":
                    ball.get_effect("explosion")
                elif hit_type == "piercing":
                    ball.get_effect("piercing")
                elif hit_type == "multiball":
                    power_type = "multiball"
                elif hit_type == "life":
                    power_type = "life"
                elif hit_type == "wide":
                    power_type = "wide"

            break

    return gained_score, power_type


def create_extra_balls(hit_ball, paddle):
    """從撞擊球的位置增加兩顆普通球。"""
    extra_balls = []

    left_ball = Ball(paddle)
    left_ball.position.update(hit_ball.position.x, hit_ball.position.y)
    left_ball.rect.center = hit_ball.rect.center
    left_ball.velocity.update(-5, hit_ball.velocity.y)
    left_ball.launched = True
    extra_balls.append(left_ball)

    right_ball = Ball(paddle)
    right_ball.position.update(hit_ball.position.x, hit_ball.position.y)
    right_ball.rect.center = hit_ball.rect.center
    right_ball.velocity.update(5, hit_ball.velocity.y)
    right_ball.launched = True
    extra_balls.append(right_ball)

    return extra_balls


def draw_lives(surface, lives):
    """在左上角用小球圖案顯示剩餘生命。"""
    for number in range(lives):
        x = 22 + number * 25
        pygame.draw.circle(surface, BALL_COLOR, (x, 24), 8)


def draw_score(surface, score, font):
    """在右上角顯示目前分數。"""
    score_text = font.render("Score: " + str(score), True, BALL_COLOR)
    score_rect = score_text.get_rect(topright=(WIDTH - 15, 10))
    surface.blit(score_text, score_rect)


def draw_game_over(surface, title_font, message_font):
    """顯示遊戲結束與重新開始提示。"""
    title = title_font.render("GAME OVER", True, EXPLOSION_COLOR)
    message = message_font.render("Press R to Restart", True, BALL_COLOR)
    title_rect = title.get_rect(center=(WIDTH // 2, HEIGHT // 2 - 25))
    message_rect = message.get_rect(center=(WIDTH // 2, HEIGHT // 2 + 25))
    surface.blit(title, title_rect)
    surface.blit(message, message_rect)


######################初始化設定######################

pygame.init()

######################遊戲視窗設定######################

screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Checkpoint 06：特殊球與生命")
clock = pygame.time.Clock()
title_font = pygame.font.Font(None, 58)
message_font = pygame.font.Font(None, 34)

######################磚塊######################

bricks = create_bricks()

######################爆炸動畫######################

explosions = []

######################底板設定######################

paddle = Paddle()

######################球設定######################

ball = Ball(paddle)

######################生命與遊戲狀態######################

lives = 3
game_over = False

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
            elif event.key == pygame.K_SPACE and not game_over:
                ball.launch()
            elif event.key == pygame.K_r and game_over:
                # 重新產生磚塊並恢復生命，開始新的一局。
                bricks = create_bricks()
                explosions = []
                lives = 3
                game_over = False
                ball.reset(paddle)

    if not game_over:
        # 取得鍵盤狀態並更新遊戲物件
        keys = pygame.key.get_pressed()
        paddle.update(keys)
        ball_lost = ball.update(paddle)

        if ball_lost:
            lives -= 1
            ball.reset(paddle)
            if lives == 0:
                game_over = True
        else:
            handle_collisions(ball, paddle, bricks, explosions)

    # 更新爆炸動畫，只留下還沒有播放完的動畫。
    active_explosions = []
    for explosion in explosions:
        if explosion.update():
            active_explosions.append(explosion)
    explosions = active_explosions

    # 清除畫面
    screen.fill(BACKGROUND)

    # 顯示磚塊、底板、球與生命
    for brick in bricks:
        brick.draw(screen)
    for explosion in explosions:
        explosion.draw(screen)
    paddle.draw(screen)
    ball.draw(screen)
    draw_lives(screen, lives)

    if game_over:
        draw_game_over(screen, title_font, message_font)

    # 更新畫面
    pygame.display.flip()

######################遊戲結束設定######################

pygame.quit()
