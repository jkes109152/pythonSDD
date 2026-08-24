#######################定義函式區########################
# 沒有輸入值，沒有返回值
from numpy import add


def show_message():
    print("開始複習 function!")


# 有輸入值，沒有返回值
def show_name(name):
    print(f"你好,{name}!")


# 有輸入值，有返回值
def add_numbers(number1, number2):
    return number1 + number2


###########主程式###########
# 呼叫沒有輸入值的函數
show_message()
# 傳入不同的名字
show_name("小明")
show_name("小華")
# 把返回值存進answer
answer = add_numbers(3, 5)
print(f"答案:{answer}")
