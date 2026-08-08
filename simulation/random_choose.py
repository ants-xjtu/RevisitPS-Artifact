import random

# 名单
people = ["马锦超", "李云广", "王清楠", "陈方舟", "唐堂", "杜金诺", "王亚男"]

# 随机抽取一个人
winners = random.sample(people, 2)
print("抽签结果：", "、".join(winners))
