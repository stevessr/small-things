# 深度推进计划（下一阶段）

## A. 绘制 / 分层阶段（必须完成）
1. 依据 `source/part_reference_crops/` 对角色进行真正 PSD 分层。
2. 对被遮挡区域进行补绘：
   - 刘海后额头与太阳穴
   - 猫耳根部
   - 侧发与后发交界
   - 蝴蝶结下压住的头发
   - 领结/领口压住的胸前衣料
   - 背心片压住的裙腰
   - 裙摆后层与腿部上缘
   - 尾巴根部与裙摆后遮挡
3. 每个可动部件建议拆成单独图层：
   - 左右眼：眼白/虹膜/高光/上睫毛/下睫毛
   - 嘴：上唇/下唇/口腔/舌头
   - 头发：前发、侧发、后发、发尾分段
   - 猫耳：耳外、耳内
   - 饰品：主蝴蝶结、花簇、叶片
   - 身体：躯干、左右大臂、左右小臂、左右手
   - 服装：上衣、衣领、胸前结、袖口、背心片、裙前/裙后/褶边
   - 尾巴：主尾与左右鳍分开

## B. Cubism 绑定顺序
1. Head Angle X/Y/Z
2. Eye Open + EyeBall X/Y
3. Brow Y + Brow Angle
4. Mouth Form + Mouth OpenY
5. Body Angle X/Y/Z
6. Hair front / side / back
7. Ears
8. Arms / hands
9. Skirt
10. Tail
11. Accessories
12. Physics + expression QA

## C. 验收门槛
- AngleX ±30 与 AngleY ±30 的 9 宫格全部检查
- Motion V2 Idle 循环无跳帧
- Expression 与 Blink / Motion 不抢参数
- 物理在极端角度不抖炸、不穿模
- 所有透明边缘无黑边、无硬锯齿
