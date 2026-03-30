

def palette():
    ryb_mode = True
    #  ryb_mode = False
    #  fuzzy = randint(5, 25) if randint(0, 5) else 0
    fuzzy = None
    scheme = 4

    if scheme == 1:
        #  analogous
        rnd_v = [-0, -5, -10, -15]
        deltas = [
            Hsv(-30, randint(-10, 5), choice(rnd_v)),
            Hsv(-15, randint(-10, 5), choice(rnd_v)),
            Hsv(+15, randint(-10, 5), choice(rnd_v)),
            Hsv(+30, randint(-10, 5), choice(rnd_v))
        ]
        if fuzzy is None:
            fuzzy = randint(0, 20) if randint(0, 5) else 0

    elif scheme == 2:
        #  complementary
        rnd_s = [+10, +20, -10, -20]
        deltas = [
            Hsv(+0, choice(rnd_s), -30),
            Hsv(+0, -10, +0),
            Hsv(+180, +0, +0),
            Hsv(+180, choice(rnd_s), -30)
        ]
        if fuzzy is None:
            fuzzy = randint(5, 25) if randint(0, 5) else 0
    elif scheme == 3:
        #  split complementary
        rnd_s = [-10, -20]
        rnd_l = [-30, -0, -30, -0]
        shuffle(rnd_l)
        deltas = [
            Hsv(+150, -10, rnd_l[0]),
            Hsv(+150, -5, rnd_l[1]),
            Hsv(+210, +5, rnd_l[2]),
            Hsv(+210, +10, rnd_l[3])
        ]
        if fuzzy is None:
            fuzzy = randint(5, 18) if randint(0, 5) else 0
    elif scheme == 4:
        #  triad
        rnd_s = [-10, -20]
        rnd_l = [-30, -0, -30, -0]
        shuffle(rnd_l)
        deltas = [
            Hsv(+120, -10, rnd_l[0]),
            Hsv(+120, -5, rnd_l[1]),
            Hsv(+240, +5, rnd_l[2]),
            Hsv(+240, +10, rnd_l[3])
        ]
        if fuzzy is None:
            fuzzy = randint(5, 18) if randint(0, 5) else 0
    elif scheme == 5:
        #  tetradic
        if fuzzy is None:
            fuzzy = randint(5, 18) if randint(0, 5) else 0



    #  fuzzy = 0
    print(fuzzy)

    base = Color(hsv=(-1, (10, 75), 98))
    colors = list()

    for i, delta in enumerate(deltas):
        print('-->', delta)
        hue = (base.hsv.h + delta.h + randint(-fuzzy, fuzzy)) % 360

        sat = base.hsv.s + delta.s + randint(-fuzzy // 2, fuzzy // 3)
        sat = min(max(5, sat), 100)

        val = base.hsv.v + delta.v + randint(-fuzzy // 2, fuzzy // 3)
        val = min(max(5, val), 100)

        color = Color(hsv=(hue, sat, val))
        if ryb_mode:
            color = color._ryb_mode()

        colors.append(color)
        print(color.hsv)
        if i == (len(deltas) // 2) - 1:
            if ryb_mode:
                colors.append(base._ryb_mode())
                print(base._ryb_mode().hsv)
            else:
                colors.append(base)
                print(base.hsv)

    #  shuffle(colors)
    return colors

    #  new = [
    #      (+0, +10, -30), (-120, -10, +0),
    #      (+120, +0, +0), (+180, +20, -30)
    #  ]


#  def interpolate(OldMin, OldMax, NewMin, NewMax):
#      OldRange = (OldMax - OldMin)
#      NewRange = (NewMax - NewMin)
#      return lambda x: (((x - OldMin) * NewRange) / OldRange) + NewMin


def harmony():
    colors = [Color(hsv=(x, 58, 98)) for x in range(0, 360, 5)]
    #  print(len(colors))
    for color in list(colors):
        #  print(color.ryb, Color._ryb_to_rgb(color.rgb))
        #  c_ryb = Color(rgb=Color._ryb_to_rgb(color.rgb))
        c_ryb = Color(ryb=color.rgb)
        c_ryb.hsv = (c_ryb.hsv.h, c_ryb.hsv.v, c_ryb.hsv.s)
        #  print(c_ryb.hsv)
        colors.append(color._ryb_mode())

    return colors
