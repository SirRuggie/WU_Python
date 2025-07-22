

import hikari


class EmojiType:
    def __init__(self, emoji_string):
        self.emoji_string = emoji_string
        self.str = emoji_string

    def __str__(self):
        return self.emoji_string

    @property
    def partial_emoji(self):
        emoji = self.emoji_string.split(':')
        animated = '<a:' in self.emoji_string
        emoji = hikari.CustomEmoji(
            name=emoji[1][1:],
            id=hikari.Snowflake(int(str(emoji[2])[:-1])),
            is_animated=animated
        )
        return emoji

class Emojis:
    def __init__(self):
        self.blank = EmojiType("<:Blank:1395727790908641370>")
        self.white_arrow_right = EmojiType("<:Arrow_White:1395727080494469141>")
        self.purple_arrow_right = EmojiType("<:Arrow_Purple:1395727972165488742>")
        self.red_arrow_right = EmojiType("<:Arrow_Red:1395728030705520702>")
        self.gold_arrow_right = EmojiType("<:Arrow_Gold:1395728112725266492>")
        self.yes = EmojiType("<:Yes:1397096942907166831>")
        self.no = EmojiType("<:No:1397096986506825778>")
        self.maybe = EmojiType("<a:Maybe:1397097100256219267>")

        #NEEDS UPDATE
        self.add = EmojiType("<:Add:1387844836916199466>")
        self.remove = EmojiType("<:Remove:1387844866008027229>")
        self.edit = EmojiType("<:Edit:1387850342473011481>")
        self.view = EmojiType("<:View:1387842874053234808>")

        self.BulletPoint = EmojiType("<:BulletPoint:1393247569970331688>")
        self.RedGem = EmojiType("<:Red_Gem:1387846215022022656>")
        self.PurpleGem = EmojiType("<:Purple_Gem:1387846189852135495>")
        self.Alert_Strobing = EmojiType("<a:Alert_Strobing:1393549773218250766>")
        self.Alert = EmojiType("<a:Alert:1393549523774603294>")
        self.FWA = EmojiType("<a:FWA:1387882523358527608>")

        # TH Emojis
        self.TH2 = EmojiType("<:TH_2:1395728426849275997>")
        self.TH3 = EmojiType("<:TH_3:1395728517299306537>")
        self.TH4 = EmojiType("<:TH_4:1395728565575618623>")
        self.TH5 = EmojiType("<:TH_5:1395728620185718796>")
        self.TH6 = EmojiType("<:TH_6:1395728668583792716>")
        self.TH7 = EmojiType("<:TH_7:1395728738334806152>")
        self.TH8 = EmojiType("<:TH_8:1395728783591608360>")
        self.TH9 = EmojiType("<:TH_9:1395728820471857266>")
        self.TH10 = EmojiType("<:TH_10:1395728880991735899>")
        self.TH11 = EmojiType("<:TH_11:1395728917339570186>")
        self.TH12 = EmojiType("<:TH_12:1395728951854501959>")
        self.TH13 = EmojiType("<:TH_13:1395728985857458261>")
        self.TH14 = EmojiType("<:TH_14:1395729011404963843>")
        self.TH15 = EmojiType("<:TH_15:1395729045962096651>")
        self.TH16 = EmojiType("<:TH_16:1395729067990319164>")
        self.TH17 = EmojiType("<:TH_17:1395729126014324837>")

        # League Emojis - not updated
        self.Champ1 = EmojiType("<:CHL_1:1387845952512983222>")
        self.Champ2 = EmojiType("<:CHL_2:1387845931231219763>")
        self.Champ3 = EmojiType("<:CHL_3:1387845906015191131>")
        self.Master1 = EmojiType("<:ML_1:1387845742080692257>")
        self.Master2 = EmojiType("<:ML_2:1387845712875880500>")
        self.Master3 = EmojiType("<:ML_3:1387845689978917025>")
        self.Crystal1 = EmojiType("<:CRL_1:1387845877405716591>")
        self.Crystal2 = EmojiType("<:CRL_2:1387845850763624488>")
        self.Crystal3 = EmojiType("<:CRL_3:1387845831679410227>")
        self.Gold1 = EmojiType("<:GL_1:1387845805460815921>")
        self.Gold2 = EmojiType("<:GL_2:1387845784116138099>")
        self.Gold3 = EmojiType("<:GL_3:1387845764524408832>")
        self.Silver1 = EmojiType("<:SL_1:1387845667145126009>")
        self.Silver2 = EmojiType("<:SL_2:1387845644487491594>")
        self.Silver3 = EmojiType("<:SL_3:1387845621095989318>")

emojis = Emojis()







