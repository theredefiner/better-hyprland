import sys
import subprocess
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
    QLineEdit, QGridLayout, QPushButton, QLabel, QFrame
)
from PyQt6.QtWidgets import QScrollArea, QWidget, QGridLayout
from PyQt6.QtCore import Qt

class DraggableContainer(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)



    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            window = self.window()
            # Wayland-er jonno native window handle force-fully create kora
            if not window.windowHandle():
                window.createWinId()
            if window.windowHandle():
                window.windowHandle().startSystemMove()


class EmojiPickerApp(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()
        self.oldPos = QPoint()
        self.setWindowTitle("hyprland-emoji-picker")
        self.setObjectName("hyprland-emoji-picker")
    

# Ekhane hobe (__init__ er baire, class er bhitor direct)
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.windowHandle():
                self.windowHandle().startSystemMove()

    def initUI(self):
        # Floating window setup (Frameless and Translucent background for frosted glass effect)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(480, 380)

        # Main container with Cool Frosted Glass Blur
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)

        self.container = QFrame(self)
        self.container.setObjectName("MainContainer")
        self.container.setStyleSheet("""
            QFrame#MainContainer {
                background-color: rgba(0, 0, 0, 0); /* Color white */
                border-radius: 10px;
                border: 0px solid rgba(255, 255, 255, 0.18);
            }
        """)
        
        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(20, 20, 20, 20)
        container_layout.setSpacing(15)

        # 1. Search Bar Layout (Google Sans Flex style with Search Icon)
        search_frame = QFrame()
        search_frame.setFixedHeight(45) 
        search_frame.setStyleSheet("""
            QFrame {
                background-color: rgba(64, 64, 64, 1.0);
                border-radius: 22px;
                padding: 1px;
            }
        """)
        search_layout = QHBoxLayout(search_frame)
        search_layout.setContentsMargins(12, 1, 12, 1)
        container_layout.addWidget(search_frame)

        search_icon = QLabel("\uf002")
        search_icon.setStyleSheet("color: white; font-size: 16px; background: transparent;")
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Type Here to Search emojis")
        self.search_input.setStyleSheet("""
            QLineEdit {
                background: transparent;
                border: white;
                color: white;
                font-family: 'Google Sans Flex', 'Segoe UI', sans-serif;
                font-size: 14px;
            }
        """)
        
        search_layout.addWidget(search_icon)
        search_layout.addWidget(self.search_input)
        container_layout.addWidget(search_frame)

        # ১. Prothome scroll_area create kore nao
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)

        self.emoji_container = QWidget()
        self.emoji_grid = QGridLayout(self.emoji_container)

        # (Tomar emoji button gulo loop chaliye ekhane self.emoji_grid-e add kora thakbe)
        # jemon: self.emoji_grid.addWidget(btn, row, col)

        self.scroll_area.setWidget(self.emoji_container)

        # ২. Scroll area-r background color ebong slim scrollbar-er QSS style
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: rgba(20, 20, 32, 0.4);
                border: none;
                border-radius: 8px;
            }
            QWidget {
                background-color: transparent;
            }
            QScrollBar:vertical {
                border: none;
                background: rgba(255, 255, 255, 0.03);
                width: 6px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 0.25);
                min-height: 20px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(255, 255, 255, 0.5);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
        

        # 2. Emoji Data with Tags/Names for Search
        self.all_emojis = [
        {"emoji": "😀", "names": ["grinning face", "happy", "smile", "joy"]},
        {"emoji": "😃", "names": ["grinning face with big eyes", "excited", "haha", "glad"]},
        {"emoji": "😄", "names": ["grinning face with smiling eyes", "laugh", "happy", "pleased"]},
        {"emoji": "😁", "names": ["beaming face with smiling eyes", "grin", "proud", "cheese"]},
        {"emoji": "😆", "names": ["grinning squinting face", "laughing", "lol", "hilarious"]},
        {"emoji": "😅", "names": ["grinning face with sweat", "relieved", "nervous", "whew"]},
        {"emoji": "🤣", "names": ["rolling on the floor laughing", "rofl", "lol", "dying"]},
        {"emoji": "😂", "names": ["face with tears of joy", "haha", "crying laughing", "funny"]},
        {"emoji": "🙂", "names": ["slightly smiling face", "fine", "okay", "polite"]},
        {"emoji": "🙃", "names": ["upside down face", "sarcasm", "silly", "irony"]},
        {"emoji": "😉", "names": ["winking face", "wink", "flirt", "joke"]},
        {"emoji": "😊", "names": ["smiling face with smiling eyes", "blush", "warm", "thankful"]},
        {"emoji": "😇", "names": ["smiling face with halo", "angel", "innocent", "good"]},
        {"emoji": "🥰", "names": ["smiling face with hearts", "love", "romantic", "crush"]},
        {"emoji": "😍", "names": ["smiling face with heart eyes", "love", "obsessed", "beautiful"]},
        {"emoji": "🤩", "names": ["star struck", "wow", "amazing", "celebrity"]},
        {"emoji": "😘", "names": ["face blowing a kiss", "kiss", "love", "muah"]},
        {"emoji": "😗", "names": ["kissing face", "kiss", "whistle", "relax"]},
        {"emoji": "😚", "names": ["kissing face with closed eyes", "romance", "blush", "sweet"]},
        {"emoji": "😙", "names": ["kissing face with smiling eyes", "kind", "affection", "warm"]},
        {"emoji": "😋", "names": ["face savoring food", "delicious", "yummy", "hungry"]},
        {"emoji": "😛", "names": ["face with tongue", "playful", "silly", "tease"]},
        {"emoji": "😜", "names": ["winking face with tongue", "crazy", "joke", "mischievous"]},
        {"emoji": "🤪", "names": ["zany face", "goofy", "wild", "wacky"]},
        {"emoji": "😝", "names": ["squinting face with tongue", "prank", "goofing", "mock"]},
        {"emoji": "🤑", "names": ["money mouth face", "rich", "cash", "wealthy"]},
        {"emoji": "🤗", "names": ["hugging face", "hug", "welcome", "warmth"]},
        {"emoji": "🤭", "names": ["face with hand over mouth", "giggle", "oops", "secret"]},
        {"emoji": "🤫", "names": ["shushing face", "quiet", "silence", "hush"]},
        {"emoji": "🤔", "names": ["thinking face", "hmm", "ponder", "wonder"]},
        {"emoji": "🤐", "names": ["zipper mouth face", "secret", "sealed", "quiet"]},
        {"emoji": "🤨", "names": ["face with raised eyebrow", "skeptical", "suspicious", "really"]},
        {"emoji": "😐", "names": ["neutral face", "meh", "indifferent", "blank"]},
        {"emoji": "😑", "names": ["expressionless face", "unimpressed", "bored", "seriously"]},
        {"emoji": "😶", "names": ["face without mouth", "speechless", "silent", "nothing to say"]},
        {"emoji": "😏", "names": ["smirking face", "smirk", "sly", "flirt", "confident"]},
        {"emoji": "😒", "names": ["unamused face", "bored", "disappointed", "annoyed"]},
        {"emoji": "🙄", "names": ["face with rolling eyes", "annoyed", "whatever", "sarcasm"]},
        {"emoji": "😬", "names": ["grimacing face", "awkward", "yikes", "nervous"]},
        {"emoji": "🤥", "names": ["lying face", "liar", "pinocchio", "fake"]},
        {"emoji": "😌", "names": ["relieved face", "peaceful", "calm", "satisfied"]},
        {"emoji": "😔", "names": ["pensive face", "sad", "remorse", "thoughtful"]},
        {"emoji": "😪", "names": ["sleepy face", "tired", "rest", "exhausted"]},
        {"emoji": "🤤", "names": ["drooling face", "desire", "tasty", "sleep"]},
        {"emoji": "😴", "names": ["sleeping face", "zzz", "bedtime", "tired"]},
        {"emoji": "😷", "names": ["face with medical mask", "sick", "doctor", "ill"]},
        {"emoji": "🤒", "names": ["face with thermometer", "fever", "sick", "flu"]},
        {"emoji": "🤕", "names": ["face with head bandage", "hurt", "injured", "accident"]},
        {"emoji": "🤢", "names": ["nauseated face", "gross", "sick", "disgust"]},
        {"emoji": "🤮", "names": ["face vomiting", "puke", "sick", "nasty"]},
        {"emoji": "🤧", "names": ["sneezing face", "cold", "allergies", "tissue"]},
        {"emoji": "🥵", "names": ["hot face", "heat", "sweat", "burning"]},
        {"emoji": "🥶", "names": ["cold face", "freezing", "ice", "winter"]},
        {"emoji": "🥴", "names": ["woozy face", "dunk", "dizzy", "fuddled"]},
        {"emoji": "😵", "names": ["dizzy face", "dead", "confused", "shocked"]},
        {"emoji": "🤯", "names": ["exploding head", "mind blown", "shock", "amazing"]},
        {"emoji": "🤠", "names": ["cowboy hat face", "sheriff", "yeehaw", "western"]},
        {"emoji": "🥳", "names": ["partying face", "celebrate", "birthday", "woohoo"]},
        {"emoji": "😎", "names": ["smiling face with sunglasses", "cool", "chill", "confident"]},
        {"emoji": "🤓", "names": ["nerd face", "geek", "smart", "studious"]},
        {"emoji": "🧐", "names": ["face with monocle", "classy", "inspect", "curious"]},
        # Peoples and body
        {"emoji": "👋", "names": ["waving hand", "hello", "goodbye", "bye"]},
        {"emoji": "🤚", "names": ["raised back of hand", "stop", "high five", "hand"]},
        {"emoji": "🖐️", "names": ["hand with fingers splayed", "five", "stop", "palm"]},
        {"emoji": "✋", "names": ["raised hand", "stop", "high five", "wait"]},
        {"emoji": "🖖", "names": ["vulcan salute", "spock", "star trek", "live long and prosper"]},
        {"emoji": "👌", "names": ["ok hand", "perfect", "deal", "correct"]},
        {"emoji": "🤌", "names": ["pinched fingers", "italian", "what do you want", "gesture"]},
        {"emoji": "🤏", "names": ["pinched hand", "small", "little bit", "tiny"]},
        {"emoji": "✌️", "names": ["victory hand", "peace", "two", "sign"]},
        {"emoji": "🤞", "names": ["crossed fingers", "luck", "hope", "promise"]},
        {"emoji": "🤟", "names": ["love you gesture", "ily", "heart", "sign"]},
        {"emoji": "🤘", "names": ["sign of the horns", "rock on", "metal", "heavy metal"]},
        {"emoji": "🤙", "names": ["call me hand", "phone", "shaka", "hang loose"]},
        {"emoji": "👈", "names": ["backhand index pointing left", "left", "direction", "look"]},
        {"emoji": "👉", "names": ["backhand index pointing right", "right", "direction", "link"]},
        {"emoji": "👆", "names": ["backhand index pointing up", "up", "above", "top"]},
        {"emoji": "🖕", "names": ["middle finger", "rude", "flip off", "insult"]},
        {"emoji": "👇", "names": ["backhand index pointing down", "down", "below", "bottom"]},
        {"emoji": "☝️", "names": ["index pointing up", "point", "one", "first"]},
        {"emoji": "👍", "names": ["thumbs up", "approve", "good", "yes"]},
        {"emoji": "👎", "names": ["thumbs down", "dislike", "bad", "no"]},
        {"emoji": "✊", "names": ["raised fist", "power", "solidarity", "fist"]},
        {"emoji": "👊", "names": ["oncoming fist", "punch", "fist bump", "brofist"]},
        {"emoji": "🤛", "names": ["left-facing fist", "fist bump", "left", "punch"]},
        {"emoji": "🤜", "names": ["right-facing fist", "fist bump", "right", "punch"]},
        {"emoji": "👏", "names": ["clapping hands", "applause", "clap", "good job"]},
        {"emoji": "🙌", "names": ["raising hands", "hooray", "success", "celebrate"]},
        {"emoji": "👐", "names": ["open hands", "hug", "open", "welcome"]},
        {"emoji": "🤲", "names": ["palms up together", "prayer", "cupped hands", "give"]},
        {"emoji": "🤝", "names": ["handshake", "deal", "agreement", "shake"]},
        {"emoji": "🙏", "names": ["folded hands", "please", "thank you", "pray"]},
        {"emoji": "✍️", "names": ["writing hand", "write", "note", "author"]},
        {"emoji": "💅", "names": ["nail polish", "beauty", "manicure", "fashion"]},
        {"emoji": "🤳", "names": ["selfie", "camera", "photo", "phone"]},
        {"emoji": "💪", "names": ["flexed biceps", "strong", "muscle", "workout"]},
        {"emoji": "🦵", "names": ["leg", "kick", "limb", "foot"]},
        {"emoji": "🦶", "names": ["foot", "step", "walk", "barefoot"]},
        {"emoji": "👂", "names": ["ear", "hear", "listen", "sound"]},
        {"emoji": "👃", "names": ["nose", "smell", "scent", "sniff"]},
        {"emoji": "👶", "names": ["baby", "infant", "child", "newborn"]},
        {"emoji": "👧", "names": ["girl", "child", "female", "youth"]},
        {"emoji": "🧒", "names": ["child", "kid", "gender neutral", "young"]},
        {"emoji": "👦", "names": ["boy", "child", "male", "youth"]},
        {"emoji": "👩", "names": ["woman", "female", "adult", "lady"]},
        {"emoji": "🧑", "names": ["person", "adult", "human", "gender neutral"]},
        {"emoji": "👨", "names": ["man", "male", "adult", "guy"]},
        {"emoji": "👩‍🦱", "names": ["woman curly hair", "curly", "female", "hairstyle"]},
        {"emoji": "👨‍🦱", "names": ["man curly hair", "curly", "male", "hairstyle"]},
        {"emoji": "👩‍🦰", "names": ["woman red hair", "ginger", "female", "redhead"]},
        {"emoji": "👨‍🦰", "names": ["man red hair", "ginger", "male", "redhead"]},
        {"emoji": "👱‍♀️", "names": ["blond woman", "blonde", "female", "hair"]},
        {"emoji": "👱‍♂️", "names": ["blond man", "blonde", "male", "hair"]},
        {"emoji": "👩‍🦳", "names": ["woman white hair", "gray hair", "female", "elderly"]},
        {"emoji": "👨‍🦳", "names": ["man white hair", "gray hair", "male", "elderly"]},
        {"emoji": "👩‍🦲", "names": ["woman bald", "hairless", "female", "smooth"]},
        {"emoji": "👨‍🦲", "names": ["man bald", "hairless", "male", "smooth"]},
        {"emoji": "👵", "names": ["old woman", "grandma", "elderly", "grandmother"]},
        {"emoji": "🧓", "names": ["older person", "elderly", "senior", "grandparent"]},
        {"emoji": "👴", "names": ["old man", "grandpa", "elderly", "grandfather"]},
        {"emoji": "🙍‍♀️", "names": ["woman frowning", "sad", "disappointed", "female"]},
        {"emoji": "🙍‍♂️", "names": ["man frowning", "sad", "disappointed", "male"]},
        {"emoji": "🙅‍♀️", "names": ["woman gesturing no", "stop", "forbidden", "female"]},
        {"emoji": "🙅‍♂️", "names": ["man gesturing no", "stop", "forbidden", "male"]},
        {"emoji": "🙆‍♀️", "names": ["woman gesturing ok", "okay", "agree", "female"]},
        {"emoji": "🙆‍♂️", "names": ["man gesturing ok", "okay", "agree", "male"]},
        {"emoji": "💁‍♀️", "names": ["woman tipping hand", "sassy", "information", "female"]},
        {"emoji": "💁‍♂️", "names": ["man tipping hand", "sassy", "information", "male"]},
        {"emoji": "🙋‍♀️", "names": ["woman raising hand", "question", "volunteer", "female"]},
        {"emoji": "🙋‍♂️", "names": ["man raising hand", "question", "volunteer", "male"]},
        {"emoji": "🧏‍♀️", "names": ["deaf woman", "deaf", "hearing", "female"]},
        {"emoji": "🧏‍♂️", "names": ["deaf man", "deaf", "hearing", "male"]},
        {"emoji": "🙇‍♀️", "names": ["woman bowing", "sorry", "respect", "female"]},
        {"emoji": "🙇‍♂️", "names": ["man bowing", "sorry", "respect", "male"]},
        {"emoji": "🤦‍♀️", "names": ["woman facepalm", "oops", "disbelief", "female"]},
        {"emoji": "🤦‍♂️", "names": ["man facepalm", "oops", "disbelief", "male"]},
        {"emoji": "🤷‍♀️", "names": ["woman shrugging", "clueless", "whatever", "female"]},
        {"emoji": "🤷‍♂️", "names": ["man shrugging", "clueless", "whatever", "male"]},
        {"emoji": "🧑‍⚕️", "names": ["health worker", "doctor", "nurse", "medical"]},
        {"emoji": "🧑‍🎓", "names": ["student", "graduate", "school", "college"]},
        {"emoji": "🧑‍🏫", "names": ["teacher", "professor", "school", "education"]},
        {"emoji": "🧑‍⚖️", "names": ["judge", "court", "law", "justice"]},
        {"emoji": "🧑‍🌾", "names": ["farmer", "agriculture", "gardener", "crop"]},
        {"emoji": "🧑‍🍳", "names": ["cook", "chef", "baking", "kitchen"]},
        {"emoji": "🧑‍🔧", "names": ["mechanic", "repair", "tools", "engineer"]},
        {"emoji": "🧑‍🏭", "names": ["factory worker", "industry", "welder", "labor"]},
        {"emoji": "🧑‍💼", "names": ["office worker", "business", "manager", "corporate"]},
        {"emoji": "🧑‍🔬", "names": ["scientist", "chemist", "lab", "research"]},
        {"emoji": "🧑‍💻", "names": ["technologist", "developer", "programmer", "coder"]},
        {"emoji": "🧑‍🎤", "names": ["singer", "rockstar", "musician", "artist"]},
        {"emoji": "🧑‍🎨", "names": ["artist", "painter", "design", "creative"]},
        {"emoji": "🧑‍✈️", "names": ["pilot", "airplane", "aviation", "flight"]},
        {"emoji": "🧑‍🚀", "names": ["astronaut", "space", "rocket", "nasa"]},
        {"emoji": "🧑‍🚒", "names": ["firefighter", "fireman", "rescue", "emergency"]},
        {"emoji": "👮‍♀️", "names": ["police woman", "cop", "law enforcement", "female"]},
        {"emoji": "👮‍♂️", "names": ["police man", "cop", "law enforcement", "male"]},
        {"emoji": "🕵️‍♀️", "names": ["woman detective", "spy", "investigate", "female"]},
        {"emoji": "🕵️‍♂️", "names": ["man detective", "spy", "investigate", "male"]},
        {"emoji": "💂‍♀️", "names": ["woman guard", "soldier", "british", "female"]},
        {"emoji": "💂‍♂️", "names": ["man guard", "soldier", "british", "male"]},
        {"emoji": "🥷", "names": ["ninja", "stealth", "shadow", "warrior"]},
        {"emoji": "👷‍♀️", "names": ["woman construction worker", "builder", "helmet", "female"]},
        {"emoji": "👷‍♂️", "names": ["man construction worker", "builder", "helmet", "male"]},
        {"emoji": "🫅", "names": ["person with crown", "monarch", "royalty", "leader"]},
        {"emoji": "👸", "names": ["princess", "royal", "tiara", "female"]},
        {"emoji": "🤴", "names": ["prince", "royal", "crown", "male"]},
        {"emoji": "👰‍♀️", "names": ["bride with veil", "wedding", "marriage", "female"]},
        {"emoji": "👰‍♂️", "names": ["man with veil", "wedding", "marriage", "male"]},
        {"emoji": "🤵‍♀️", "names": ["woman in tuxedo", "formal", "suit", "female"]},
        {"emoji": "🤵‍♂️", "names": ["man in tuxedo", "formal", "suit", "male"]},
        {"emoji": "🤰", "names": ["pregnant woman", "baby", "mom", "pregnancy"]},
        {"emoji": "🤱", "names": ["breastfeeding", "baby", "mother", "feeding"]},
        {"emoji": "👼", "names": ["baby angel", "cherub", "cupid", "innocent"]},
        {"emoji": "🎅", "names": ["santa claus", "christmas", "st nick", "holiday"]},
        {"emoji": "🤶", "names": ["mrs claus", "christmas", "holiday", "female"]},
        {"emoji": "🧑‍🎄", "names": ["mx claus", "christmas", "holiday", "gender neutral"]},
        {"emoji": "🦸‍♀️", "names": ["woman superhero", "hero", "power", "female"]},
        {"emoji": "🦸‍♂️", "names": ["man superhero", "hero", "power", "male"]},
        {"emoji": "🦹‍♀️", "names": ["woman supervillain", "villain", "evil", "female"]},
        {"emoji": "🦹‍♂️", "names": ["man supervillain", "villain", "evil", "male"]},
        {"emoji": "🧙‍♀️", "names": ["woman mage", "witch", "wizard", "female"]},
        {"emoji": "🧙‍♂️", "names": ["man mage", "wizard", "warlock", "male"]},
        {"emoji": "🧚‍♀️", "names": ["woman fairy", "magic", "wings", "female"]},
        {"emoji": "🧚‍♂️", "names": ["man fairy", "magic", "wings", "male"]},
        {"emoji": "🧛‍♀️", "names": ["woman vampire", "dracula", "goth", "female"]},
        # Animals and Nature
        {"emoji": "🐵", "names": ["monkey face", "animal", "cute", "circus"]},
        {"emoji": "🐒", "names": ["monkey", "animal", "ape", "jungle"]},
        {"emoji": "🦍", "names": ["gorilla", "animal", "ape", "strong"]},
        {"emoji": "🦧", "names": ["orangutan", "animal", "ape", "forest"]},
        {"emoji": "🐶", "names": ["dog face", "animal", "pet", "puppy"]},
        {"emoji": "🐕", "names": ["dog", "animal", "pet", "hound"]},
        {"emoji": "🦮", "names": ["guide dog", "service animal", "blind", "assistance"]},
        {"emoji": "🐕‍🦺", "names": ["service dog", "assistance", "pet", "working"]},
        {"emoji": "🐩", "names": ["poodle", "dog", "pet", "fancy"]},
        {"emoji": "🐺", "names": ["wolf", "animal", "wild", "howl"]},
        {"emoji": "🦊", "names": ["fox", "animal", "wild", "sly"]},
        {"emoji": "🦝", "names": ["raccoon", "animal", "trash panda", "scavenger"]},
        {"emoji": "🐱", "names": ["cat face", "animal", "pet", "kitten"]},
        {"emoji": "🐈", "names": ["cat", "animal", "pet", "feline"]},
        {"emoji": "🐈‍⬛", "names": ["black cat", "animal", "pet", "halloween"]},
        {"emoji": "🦁", "names": ["lion", "animal", "wild", "king"]},
        {"emoji": "🐯", "names": ["tiger face", "animal", "wild", "stripes"]},
        {"emoji": "🐅", "names": ["tiger", "animal", "wild", "feline"]},
        {"emoji": "🐆", "names": ["leopard", "animal", "wild", "spots"]},
        {"emoji": "🐴", "names": ["horse face", "animal", "pet", "pony"]},
        {"emoji": "🐎", "names": ["horse", "animal", "equestrian", "racing"]},
        {"emoji": "🦄", "names": ["unicorn", "animal", "magic", "fantasy"]},
        {"emoji": "🦓", "names": ["zebra", "animal", "wild", "stripes"]},
        {"emoji": "🦌", "names": ["deer", "animal", "forest", "buck"]},
        {"emoji": "🦬", "names": ["bison", "animal", "buffalo", "wild"]},
        {"emoji": "🐮", "names": ["cow face", "animal", "farm", "calf"]},
        {"emoji": "🐂", "names": ["ox", "animal", "farm", "bull"]},
        {"emoji": "🐃", "names": ["water buffalo", "animal", "farm", "swamp"]},
        {"emoji": "🐄", "names": ["cow", "animal", "farm", "milk"]},
        {"emoji": "🐷", "names": ["pig face", "animal", "farm", "piglet"]},
        {"emoji": "🐖", "names": ["pig", "animal", "farm", "swine"]},
        {"emoji": "🐗", "names": ["boar", "animal", "wild", "hog"]},
        {"emoji": "🐽", "names": ["pig nose", "animal", "snout", "farm"]},
        {"emoji": "🐏", "names": ["ram", "animal", "farm", "horn"]},
        {"emoji": "🐑", "names": ["ewe", "sheep", "animal", "farm"]},
        {"emoji": "🐐", "names": ["goat", "animal", "farm", "goat"]},
        {"emoji": "🐪", "names": ["camel", "animal", "desert", "hump"]},
        {"emoji": "🐫", "names": ["two-hump camel", "animal", "desert", "bactrian"]},
        {"emoji": "🦙", "names": ["llama", "animal", "alpaca", "wool"]},
        {"emoji": "🦒", "names": ["giraffe", "animal", "wild", "tall"]},
        {"emoji": "🐘", "names": ["elephant", "animal", "wild", "trunk"]},
        {"emoji": "🦣", "names": ["mammoth", "animal", "extinct", "tusk"]},
        {"emoji": "🦏", "names": ["rhinoceros", "animal", "wild", "horn"]},
        {"emoji": "🦛", "names": ["hippopotamus", "animal", "wild", "river"]},
        {"emoji": "🐭", "names": ["mouse face", "animal", "rodent", "cute"]},
        {"emoji": "🐁", "names": ["mouse", "animal", "rodent", "pest"]},
        {"emoji": "🐀", "names": ["rat", "animal", "rodent", "sewer"]},
        {"emoji": "🐹", "names": ["hamster", "animal", "pet", "fluffy"]},
        {"emoji": "🐰", "names": ["rabbit face", "animal", "pet", "bunny"]},
        {"emoji": "🐇", "names": ["rabbit", "animal", "pet", "bunny"]},
        {"emoji": "🐿️", "names": ["chipmunk", "animal", "forest", "nut"]},
        {"emoji": "🦫", "names": ["beaver", "animal", "dam", "rodent"]},
        {"emoji": "🦔", "names": ["hedgehog", "animal", "spiky", "pet"]},
        {"emoji": "🦇", "names": ["bat", "animal", "vampire", "halloween"]},
        {"emoji": "🐻", "names": ["bear", "animal", "wild", "grizzly"]},
        {"emoji": "🐻‍❄️", "names": ["polar bear", "animal", "arctic", "snow"]},
        {"emoji": "🐨", "names": ["koala", "animal", "australia", "bear"]},
        {"emoji": "🐼", "names": ["panda", "animal", "bamboo", "china"]},
        {"emoji": "🦥", "names": ["sloth", "animal", "slow", "jungle"]},
        {"emoji": "🦦", "names": ["otter", "animal", "river", "cute"]},
        {"emoji": "🦨", "names": ["skunk", "animal", "smelly", "stink"]},
        {"emoji": "🦘", "names": ["kangaroo", "animal", "australia", "pouch"]},
        {"emoji": "🦡", "names": ["badger", "animal", "wild", "burrow"]},
        {"emoji": "🦃", "names": ["turkey", "animal", "bird", "thanksgiving"]},
        {"emoji": "🐔", "names": ["chicken", "animal", "bird", "farm"]},
        {"emoji": "🐓", "names": ["rooster", "animal", "bird", "cock"]},
        {"emoji": "🐣", "names": ["hatching chick", "animal", "bird", "egg"]},
        {"emoji": "🐤", "names": ["baby chick", "animal", "bird", "cute"]},
        {"emoji": "🐥", "names": ["front-facing baby chick", "animal", "bird", "yellow"]},
        {"emoji": "🐦", "names": ["bird", "animal", "nature", "fly"]},
        {"emoji": "🐧", "names": ["penguin", "animal", "bird", "antarctic"]},
        {"emoji": "🕊️", "names": ["dove", "animal", "bird", "peace"]},
        {"emoji": "🦅", "names": ["eagle", "animal", "bird", "predator"]},
        {"emoji": "🦆", "names": ["duck", "animal", "bird", "mallard"]},
        {"emoji": "🦢", "names": ["swan", "animal", "bird", "elegant"]},
        {"emoji": "🦉", "names": ["owl", "animal", "bird", "wise"]},
        {"emoji": "🦤", "names": ["dodo", "animal", "bird", "extinct"]},
        {"emoji": "🦩", "names": ["flamingo", "animal", "bird", "pink"]},
        {"emoji": "🦚", "names": ["peacock", "animal", "bird", "feathers"]},
        {"emoji": "🦜", "names": ["parrot", "animal", "bird", "tropical"]},
        {"emoji": "🐸", "names": ["frog", "animal", "amphibian", "toad"]},
        {"emoji": "🐊", "names": ["crocodile", "animal", "alligator", "swamp"]},
        {"emoji": "🐢", "names": ["turtle", "animal", "tortoise", "shell"]},
        {"emoji": "🦎", "names": ["lizard", "animal", "reptile", "gecko"]},
        {"emoji": "🐍", "names": ["snake", "animal", "reptile", "serpent"]},
        {"emoji": "🐲", "names": ["dragon face", "animal", "mythical", "fantasy"]},
        {"emoji": "🐉", "names": ["dragon", "animal", "mythical", "chinese"]},
        {"emoji": "🦕", "names": ["sauropod", "dinosaur", "animal", "brontosaurus"]},
        {"emoji": "🦖", "names": ["t-rex", "dinosaur", "animal", "predator"]},
        {"emoji": "🐳", "names": ["spouting whale", "animal", "ocean", "sea"]},
        {"emoji": "🐋", "names": ["whale", "animal", "ocean", "sea"]},
        {"emoji": "🐬", "names": ["dolphin", "animal", "ocean", "intelligent"]},
        {"emoji": "🦭", "names": ["seal", "animal", "ocean", "aquarium"]},
        {"emoji": "🐟", "names": ["fish", "animal", "ocean", "sea"]},
        {"emoji": "🐠", "names": ["tropical fish", "animal", "ocean", "reef"]},
        {"emoji": "🐡", "names": ["blowfish", "animal", "ocean", "puffer"]},
        {"emoji": "🦈", "names": ["shark", "animal", "ocean", "predator"]},
        {"emoji": "🐙", "names": ["octopus", "animal", "ocean", "tentacles"]},
        {"emoji": "🐚", "names": ["spiral shell", "beach", "ocean", "sea"]},
        {"emoji": "🐌", "names": ["snail", "animal", "bug", "slow"]},
        {"emoji": "🦋", "names": ["butterfly", "animal", "bug", "insect"]},
        {"emoji": "🐛", "names": ["bug", "caterpillar", "insect", "nature"]},
        {"emoji": "🐜", "names": ["ant", "animal", "bug", "insect"]},
        {"emoji": "🐝", "names": ["honeybee", "animal", "bug", "insect"]},
        {"emoji": "🪲", "names": ["beetle", "animal", "bug", "insect"]},
        {"emoji": "🐞", "names": ["lady beetle", "ladybug", "bug", "insect"]},
        {"emoji": "🦗", "names": ["cricket", "animal", "bug", "grasshopper"]},
        {"emoji": "🪳", "names": ["cockroach", "animal", "bug", "pest"]},
        {"emoji": "🕷️", "names": ["spider", "animal", "bug", "arachnid"]},
        {"emoji": "🕸️", "names": ["spider web", "spider", "halloween", "net"]},
        {"emoji": "🦂", "names": ["scorpion", "animal", "bug", "arachnid"]},
        {"emoji": " mosquito", "names": ["mosquito", "animal", "bug", "pest"]},
        {"emoji": "🪰", "names": ["fly", "animal", "bug", "pest"]},
        {"emoji": "🪱", "names": ["worm", "animal", "bug", "earthworm"]},
        {"emoji": "🦠", "names": ["microbe", "bacteria", "virus", "science"]},
        {"emoji": "💐", "names": ["bouquet", "flower", "nature", "gift"]},
        {"emoji": "🌸", "names": ["cherry blossom", "flower", "nature", "spring"]},
        {"emoji": "💮", "names": ["white flower", "nature", "stamp", "japanese"]},
        {"emoji": "Lotus", "names": ["lotus", "flower", "nature", "pure"]},
        {"emoji": "🌹", "names": ["rose", "flower", "nature", "love"]},
        {"emoji": "🥀", "names": ["wilted flower", "flower", "nature", "sad"]},
        {"emoji": "🌺", "names": ["hibiscus", "flower", "nature", "tropical"]},
        {"emoji": "🌻", "names": ["sunflower", "flower", "nature", "yellow"]},
        {"emoji": "🌼", "names": ["blossom", "flower", "nature", "yellow"]},
        {"emoji": "🌷", "names": ["tulip", "flower", "nature", "spring"]},
        {"emoji": "🌱", "names": ["seedling", "plant", "nature", "grow"]},
        {"emoji": "🪴", "names": ["potted plant", "plant", "nature", "home"]},
        {"emoji": "🌲", "names": ["evergreen tree", "tree", "nature", "forest"]},
        {"emoji": "🌳", "names": ["deciduous tree", "tree", "nature", "forest"]},
        {"emoji": "🌴", "names": ["palm tree", "tree", "nature", "tropical"]},
        {"emoji": "🌵", "names": ["cactus", "plant", "nature", "desert"]},
        # Food and Drinks
        {"emoji": "🍇", "names": ["grapes", "fruit", "food", "wine"]},
        {"emoji": "🍈", "names": ["melon", "fruit", "food", "cantaloupe"]},
        {"emoji": "🍉", "names": ["watermelon", "fruit", "food", "summer"]},
        {"emoji": "🍊", "names": ["tangerine", "fruit", "food", "orange"]},
        {"emoji": "🍋", "names": ["lemon", "fruit", "food", "sour"]},
        {"emoji": "🍌", "names": ["banana", "fruit", "food", "yellow"]},
        {"emoji": "🍍", "names": ["pineapple", "fruit", "food", "tropical"]},
        {"emoji": "🥭", "names": ["mango", "fruit", "food", "sweet"]},
        {"emoji": "🍎", "names": ["red apple", "fruit", "food", "macintosh"]},
        {"emoji": "🍏", "names": ["green apple", "fruit", "food", "granny smith"]},
        {"emoji": " pear", "names": ["pear", "fruit", "food", "orchard"]},
        {"emoji": "🍑", "names": ["peach", "fruit", "food", "sweet"]},
        {"emoji": "🍒", "names": ["cherries", "fruit", "food", "berry"]},
        {"emoji": "🍓", "names": ["strawberry", "fruit", "food", "berry"]},
        {"emoji": "🫐", "names": ["blueberries", "fruit", "food", "berry"]},
        {"emoji": "🥝", "names": ["kiwi fruit", "fruit", "food", "kiwi"]},
        {"emoji": "🍅", "names": ["tomato", "fruit", "vegetable", "food"]},
        {"emoji": "🫒", "names": ["olive", "food", "vegetable", "martini"]},
        {"emoji": "🥥", "names": ["coconut", "fruit", "food", "tropical"]},
        {"emoji": "🥑", "names": ["avocado", "fruit", "food", "guacamole"]},
        {"emoji": "🍆", "names": ["eggplant", "vegetable", "food", "aubergine"]},
        {"emoji": "🥔", "names": ["potato", "vegetable", "food", "carb"]},
        {"emoji": "🥕", "names": ["carrot", "vegetable", "food", "orange"]},
        {"emoji": "🌽", "names": ["ear of corn", "vegetable", "food", "maize"]},
        {"emoji": "🌶️", "names": ["hot pepper", "chili", "spicy", "food"]},
        {"emoji": "🫑", "names": ["bell pepper", "vegetable", "food", "capsicum"]},
        {"emoji": "🥒", "names": ["cucumber", "vegetable", "food", "pickle"]},
        {"emoji": "🥬", "names": ["leafy green", "vegetable", "food", "lettuce"]},
        {"emoji": "🥦", "names": ["broccoli", "vegetable", "food", "green"]},
        {"emoji": "🧄", "names": ["garlic", "vegetable", "food", "spice"]},
        {"emoji": "🧅", "names": ["onion", "vegetable", "food", "spice"]},
        {"emoji": "🍄", "names": ["mushroom", "fungus", "food", "truffle"]},
        {"emoji": "🥜", "names": ["peanuts", "nut", "food", "snack"]},
        {"emoji": "🫘", "names": ["beans", "legume", "food", "kidney bean"]},
        {"emoji": "🌰", "names": ["chestnut", "nut", "food", "roast"]},
        {"emoji": "🍞", "names": ["bread", "loaf", "food", "bakery"]},
        {"emoji": "🥐", "names": ["croissant", "bread", "bakery", "pastry"]},
        {"emoji": "🥖", "names": ["baguette bread", "french", "bakery", "loaf"]},
        {"emoji": "🫓", "names": ["flatbread", "naan", "pita", "food"]},
        {"emoji": "🥨", "names": ["pretzel", "snack", "bakery", "salty"]},
        {"emoji": "🥯", "names": ["bagel", "bakery", "bread", "breakfast"]},
        {"emoji": "🥞", "names": ["pancakes", "breakfast", "food", "syrup"]},
        {"emoji": "🧇", "names": ["waffle", "breakfast", "food", "syrup"]},
        {"emoji": "🧀", "names": ["cheese wedge", "dairy", "food", "cheddar"]},
        {"emoji": "🍖", "names": ["meat on bone", "meat", "food", "barbecue"]},
        {"emoji": "🍗", "names": ["poultry leg", "chicken", "meat", "drumstick"]},
        {"emoji": "🥩", "names": ["cut of meat", "steak", "beef", "food"]},
        {"emoji": "🥓", "names": ["bacon", "meat", "pork", "breakfast"]},
        {"emoji": "🍔", "names": ["hamburger", "burger", "fast food", "beef"]},
        {"emoji": "🍟", "names": ["french fries", "fast food", "snack", "potato"]},
        {"emoji": "🍕", "names": ["pizza", "food", "slice", "fast food"]},
        {"emoji": "🌭", "names": ["hot dog", "fast food", "sausage", "frankfurter"]},
        {"emoji": "🥪", "names": ["sandwich", "lunch", "bread", "food"]},
        {"emoji": "🌮", "names": ["taco", "mexican", "fast food", "shell"]},
        {"emoji": "🌯", "names": ["burrito", "mexican", "fast food", "wrap"]},
        {"emoji": "🫔", "names": ["tamale", "mexican", "food", "corn"]},
        {"emoji": "🥙", "names": ["stuffed flatbread", "gyro", "falafel", "kebab"]},
        {"emoji": "🧆", "names": ["falafel", "chickpea", "food", "mediterranean"]},
        {"emoji": "🍳", "names": ["cooking", "egg", "breakfast", "pan"]},
        {"emoji": "🥘", "names": ["shallow pan of food", "paella", "dinner", "stew"]},
        {"emoji": "🍲", "names": ["pot of food", "soup", "stew", "hotpot"]},
        {"emoji": "🫕", "names": ["fondue", "cheese", "chocolate", "pot"]},
        {"emoji": "🥣", "names": ["bowl with spoon", "cereal", "soup", "oatmeal"]},
        {"emoji": "🥗", "names": ["green salad", "healthy", "food", "vegetable"]},
        {"emoji": "🍿", "names": ["popcorn", "snack", "movie", "corn"]},
        {"emoji": "🧈", "names": ["butter", "dairy", "food", "spread"]},
        {"emoji": "🧂", "names": ["salt", "spice", "seasoning", "shaker"]},
        {"emoji": "🥫", "names": ["canned food", "soup", "tin", "pantry"]},
        {"emoji": "🍱", "names": ["bento box", "japanese", "lunch", "sushi"]},
        {"emoji": "🍘", "names": ["rice cracker", "japanese", "snack", "food"]},
        {"emoji": "🍙", "names": ["rice ball", "japanese", "onigiri", "food"]},
        {"emoji": "🍚", "names": ["cooked rice", "bowl", "japanese", "grain"]},
        {"emoji": "🍛", "names": ["curry rice", "indian", "spice", "dinner"]},
        {"emoji": "🍜", "names": ["steaming bowl", "ramen", "noodles", "soup"]},
        {"emoji": "🍝", "names": ["spaghetti", "pasta", "italian", "noodles"]},
        {"emoji": "🍠", "names": ["roasted sweet potato", "yam", "snack", "food"]},
        {"emoji": "🍢", "names": ["oden", "japanese", "skewers", "seafood"]},
        {"emoji": "🍣", "names": ["sushi", "japanese", "raw fish", "rice"]},
        {"emoji": "🍤", "names": ["fried shrimp", "tempura", "seafood", "japanese"]},
        {"emoji": "🍥", "names": ["fish cake with swirl", "narutomaki", "ramen", "japanese"]},
        {"emoji": "🥮", "names": ["mooncake", "chinese", "festival", "bakery"]},
        {"emoji": "🍡", "names": ["dango", "japanese", "sweet", "dessert"]},
        {"emoji": "🥟", "names": ["dumpling", "potsticker", "chinese", "pierogi"]},
        {"emoji": "🥠", "names": ["fortune cookie", "chinese", "prophecy", "snack"]},
        {"emoji": "🥡", "names": ["takeout box", "chinese", "delivery", "lunch"]},
        {"emoji": "🦪", "names": ["oyster", "seafood", "shellfish", "pearl"]},
        {"emoji": "🍦", "names": ["soft ice cream", "dessert", "sweet", "cone"]},
        {"emoji": "🍧", "names": ["shaved ice", "dessert", "sweet", "syrup"]},
        {"emoji": "🍨", "names": ["ice cream", "dessert", "sweet", "scoop"]},
        {"emoji": "🍩", "names": ["doughnut", "donut", "dessert", "bakery"]},
        {"emoji": "🍪", "names": ["cookie", "biscuit", "dessert", "chocolate chip"]},
        {"emoji": "🎂", "names": ["birthday cake", "celebration", "dessert", "candles"]},
        {"emoji": "🍰", "names": ["shortcake", "cake", "dessert", "slice"]},
        {"emoji": "🧁", "names": ["cupcake", "muffin", "dessert", "bakery"]},
        {"emoji": "🥧", "names": ["pie", "tart", "dessert", "bakery"]},
        {"emoji": "🍫", "names": ["chocolate bar", "candy", "sweet", "dessert"]},
        {"emoji": "🍬", "names": ["candy", "sweet", "treat", "sugar"]},
        {"emoji": "🍭", "names": ["lollipop", "candy", "sweet", "sucker"]},
        {"emoji": "🍮", "names": ["custard", "flan", "pudding", "dessert"]},
        {"emoji": "🍯", "names": ["honey pot", "sweet", "bee", "jar"]},
        {"emoji": "🍼", "names": ["baby bottle", "milk", "drink", "infant"]},
        {"emoji": "🥛", "names": ["glass of milk", "dairy", "drink", "beverage"]},
        {"emoji": "☕", "names": ["hot beverage", "coffee", "tea", "cup"]},
        {"emoji": "🫖", "names": ["teapot", "tea", "beverage", "herbal"]},
        {"emoji": "🍵", "names": ["teacup without handle", "matcha", "green tea", "japanese"]},
        {"emoji": "🍶", "names": ["sake", "japanese", "alcohol", "wine"]},
        {"emoji": "🍾", "names": ["bottle with popping cork", "champagne", "celebrate", "wine"]},
        {"emoji": "🍷", "names": ["wine glass", "alcohol", "merlot", "beverage"]},
        {"emoji": "🍸", "names": ["cocktail glass", "martini", "alcohol", "drink"]},
        {"emoji": "🍹", "names": ["tropical drink", "cocktail", "alcohol", "beach"]},
        {"emoji": "🍺", "names": ["beer mug", "alcohol", "brew", "pub"]},
        {"emoji": "🍻", "names": ["clinking beer mugs", "cheers", "celebrate", "alcohol"]},
        {"emoji": "🥂", "names": ["clinking glasses", "toast", "celebrate", "champagne"]},
        {"emoji": "🥃", "names": ["tumbler glass", "whiskey", "bourbon", "alcohol"]},
        {"emoji": "🫗", "names": ["pouring liquid", "drink", "spill", "glass"]},
        {"emoji": "🥤", "names": ["cup with straw", "soda", "juice", "beverage"]},
        {"emoji": "🧋", "names": ["bubble tea", "boba", "milk tea", "tapioca"]},
        {"emoji": "🧃", "names": ["juice box", "drink", "fruit", "box"]},
        {"emoji": "🧉", "names": ["mate", "herbal", "tea", "drink"]},
        {"emoji": "🧊", "names": ["ice cube", "cold", "water", "freeze"]},
        # Travel and Places
        {"emoji": "🚗", "names": ["automobile", "car", "travel", "drive"]},
        {"emoji": "🚕", "names": ["taxi", "cab", "travel", "uber"]},
        {"emoji": "🚙", "names": ["sport utility vehicle", "suv", "car", "travel"]},
        {"emoji": "🚌", "names": ["bus", "transit", "vehicle", "travel"]},
        {"emoji": "🚎", "names": ["trolleybus", "transit", "bus", "travel"]},
        {"emoji": "🏎️", "names": ["racing car", "f1", "speed", "sports"]},
        {"emoji": "🚓", "names": ["police car", "cop", "law enforcement", "emergency"]},
        {"emoji": "🚑", "names": ["ambulance", "hospital", "emergency", "medical"]},
        {"emoji": "🚒", "names": ["fire engine", "truck", "emergency", "rescue"]},
        {"emoji": "🚐", "names": ["minivan", "car", "travel", "van"]},
        {"emoji": "🛻", "names": ["pickup truck", "vehicle", "truck", "drive"]},
        {"emoji": "🚚", "names": ["delivery truck", "shipping", "cargo", "move"]},
        {"emoji": "🚛", "names": ["articulated lorry", "semi", "truck", "cargo"]},
        {"emoji": "🚜", "names": ["tractor", "farm", "agriculture", "vehicle"]},
        {"emoji": "🦯", "names": ["white cane", "accessibility", "blind", "walk"]},
        {"emoji": "🦽", "names": ["manual wheelchair", "accessibility", "disabled", "mobility"]},
        {"emoji": "🦼", "names": ["motorized wheelchair", "accessibility", "disabled", "mobility"]},
        {"emoji": "🛺", "names": ["auto rickshaw", "tuk tuk", "travel", "asia"]},
        {"emoji": "🚲", "names": ["bicycle", "bike", "cycle", "travel"]},
        {"emoji": "🛴", "names": ["kick scooter", "ride", "skate", "scooter"]},
        {"emoji": "🛹", "names": ["skateboard", "skate", "board", "sports"]},
        {"emoji": "🛼", "names": ["roller skate", "skating", "wheels", "sports"]},
        {"emoji": "🛵", "names": ["motor scooter", "vespa", "moped", "ride"]},
        {"emoji": "🏍️", "names": ["motorcycle", "bike", "motorbike", "ride"]},
        {"emoji": "🛞", "names": ["wheel", "tire", "car", "drive"]},
        {"emoji": "🚏", "names": ["bus stop", "transit", "wait", "sign"]},
        {"emoji": "🛣️", "names": ["highway", "road", "freeway", "travel"]},
        {"emoji": "🛤️", "names": ["railway track", "train", "travel", "rail"]},
        {"emoji": "🛢️", "names": ["oil drum", "fuel", "petroleum", "barrel"]},
        {"emoji": "⛽", "names": ["fuel pump", "gas station", "petrol", "car"]},
        {"emoji": "🚨", "names": ["police car light", "siren", "emergency", "alert"]},
        {"emoji": "🚥", "names": ["horizontal traffic light", "stop", "go", "sign"]},
        {"emoji": "🚦", "names": ["vertical traffic light", "stop", "go", "sign"]},
        {"emoji": "🛑", "names": ["stop sign", "halt", "traffic", "sign"]},
        {"emoji": "🚧", "names": ["construction", "barrier", "caution", "warning"]},
        {"emoji": "⚓", "names": ["anchor", "ship", "ocean", "nautical"]},
        {"emoji": "🛟", "names": ["ring buoy", "life saver", "safety", "pool"]},
        {"emoji": "⛵", "names": ["sailboat", "boat", "yacht", "ocean"]},
        {"emoji": "🛶", "names": ["canoe", "boat", "paddle", "river"]},
        {"emoji": "🚤", "names": ["speedboat", "boat", "ship", "fast"]},
        {"emoji": "🛳️", "names": ["passenger ship", "cruise", "travel", "ocean"]},
        {"emoji": "⛴️", "names": ["ferry", "boat", "transit", "travel"]},
        {"emoji": "🛥️", "names": ["motor boat", "yacht", "luxury", "ocean"]},
        {"emoji": "🚢", "names": ["ship", "boat", "cargo", "ocean"]},
        {"emoji": "✈️", "names": ["airplane", "flight", "travel", "jet"]},
        {"emoji": "🛫", "names": ["airplane departure", "takeoff", "flight", "travel"]},
        {"emoji": "🛬", "names": ["airplane arrival", "landing", "flight", "travel"]},
        {"emoji": "🪂", "names": ["parachute", "skydiving", "jump", "fly"]},
        {"emoji": "💺", "names": ["seat", "flight", "chair", "travel"]},
        {"emoji": "🚁", "names": ["helicopter", "chopper", "fly", "flight"]},
        {"emoji": "🚟", "names": ["suspension railway", "transit", "train", "travel"]},
        {"emoji": "🚠", "names": ["mountain cableway", "gondola", "lift", "ski"]},
        {"emoji": "🚡", "names": ["aerial tramway", "gondola", "lift", "travel"]},
        {"emoji": "🛰️", "names": ["satellite", "space", "orbit", "nasa"]},
        {"emoji": "🚀", "names": ["rocket", "space", "nasa", "launch"]},
        {"emoji": "🛸", "names": ["flying saucer", "ufo", "alien", "space"]},
        {"emoji": "🪐", "names": ["ringed planet", "saturn", "space", "astronomy"]},
        {"emoji": "🌠", "names": ["shooting star", "wish", "space", "astronomy"]},
        {"emoji": "🌌", "names": ["milky way", "space", "stars", "galaxy"]},
        {"emoji": "☀️", "names": ["sun", "weather", "hot", "summer"]},
        {"emoji": "🌤️", "names": ["sun behind small cloud", "weather", "sunny", "cloudy"]},
        {"emoji": "⛅", "names": ["sun behind cloud", "weather", "sunny", "cloudy"]},
        {"emoji": "🌥️", "names": ["sun behind large cloud", "weather", "cloudy", "overcast"]},
        {"emoji": "🌦️", "names": ["sun behind rain cloud", "weather", "rain", "shower"]},
        {"emoji": "🌧️", "names": ["rain cloud", "weather", "rain", "storm"]},
        {"emoji": "⛈️", "names": ["cloud with lightning and rain", "weather", "thunderstorm", "storm"]},
        {"emoji": "🌩️", "names": ["cloud with lightning", "weather", "lightning", "storm"]},
        {"emoji": "🌨️", "names": ["snow cloud", "weather", "snow", "winter"]},
        {"emoji": "❄️", "names": ["snowflake", "winter", "cold", "snow"]},
        {"emoji": "🌬️", "names": ["wind face", "weather", "wind", "blow"]},
        {"emoji": "💨", "names": ["dash", "fast", "wind", "run"]},
        {"emoji": "🌪️", "names": ["tornado", "weather", "storm", "whirlwind"]},
        {"emoji": "🌫️", "names": ["fog", "weather", "mist", "haze"]},
        {"emoji": "🌈", "names": ["rainbow", "weather", "color", "nature"]},
        {"emoji": "🏖️", "names": ["beach with umbrella", "beach", "summer", "vacation"]},
        {"emoji": "🏜️", "names": ["desert", "sand", "hot", "safari"]},
        {"emoji": "🏝️", "names": ["desert island", "island", "tropical", "vacation"]},
        {"emoji": "🏞️", "names": ["national park", "nature", "forest", "river"]},
        {"emoji": "🏔️", "names": ["snow-capped mountain", "mountain", "winter", "hike"]},
        {"emoji": "⛰️", "names": ["mountain", "nature", "hill", "climb"]},
        {"emoji": "🌋", "names": ["volcano", "lava", "nature", "eruption"]},
        {"emoji": "🗻", "names": ["mount fuji", "mountain", "japan", "nature"]},
        {"emoji": "⛺", "names": ["tent", "camping", "outdoors", "nature"]},
        {"emoji": "🏠", "names": ["house", "home", "building", "residential"]},
        {"emoji": "🏡", "names": ["house with garden", "home", "suburb", "property"]},
        {"emoji": "🏢", "names": ["office building", "work", "corporate", "skyscraper"]},
        {"emoji": "🏣", "names": ["japanese post office", "mail", "building", "postal"]},
        {"emoji": "🏤", "names": ["post office", "mail", "building", "postal"]},
        {"emoji": "病院", "names": ["hospital", "medical", "doctor", "building"]},
        {"emoji": "🏦", "names": ["bank", "money", "finance", "building"]},
        {"emoji": "🏨", "names": ["hotel", "travel", "stay", "building"]},
        {"emoji": "🏩", "names": ["love hotel", "motel", "building", "japan"]},
        {"emoji": "🏪", "names": ["convenience store", "shop", "market", "7-eleven"]},
        {"emoji": "🏫", "names": ["school", "education", "building", "college"]},
        {"emoji": "🏬", "names": ["department store", "mall", "shop", "shopping"]},
        {"emoji": "🏭", "names": ["factory", "industry", "building", "pollution"]},
        {"emoji": "🏯", "names": ["japanese castle", "history", "landmark", "travel"]},
        {"emoji": "🏰", "names": ["castle", "history", "landmark", "fantasy"]},
        {"emoji": "💒", "names": ["wedding", "church", "marriage", "chapel"]},
        {"emoji": "🗼", "names": ["tokyo tower", "landmark", "japan", "travel"]},
        {"emoji": "🗽", "names": ["statue of liberty", "landmark", "new york", "travel"]},
        {"emoji": "教堂", "names": ["church", "religion", "christian", "building"]},
        {"emoji": "清真寺", "names": ["mosque", "religion", "islam", "building"]},
        {"emoji": "힌두교 사원", "names": ["hindu temple", "religion", "prayer", "building"]},
        {"emoji": " synagogue", "names": ["synagogue", "religion", "jewish", "building"]},
        {"emoji": "⛩️", "names": ["shinto shrine", "religion", "japan", "landmark"]},
        {"emoji": "🕋", "names": ["kaaba", "religion", "islam", "mecca"]},
        {"emoji": "⛲", "names": ["fountain", "park", "water", "decor"]},
        {"emoji": "⛺", "names": ["tent", "camping", "nature", "outdoors"]},
        {"emoji": "🌁", "names": ["foggy", "bridge", "san francisco", "landmark"]},
        {"emoji": "🌃", "names": ["night with stars", "city", "dark", "sky"]},
        {"emoji": "🏙️", "names": ["cityscape", "skyline", "city", "buildings"]},
        {"emoji": "🌅", "names": ["sunrise", "morning", "sun", "dawn"]},
        {"emoji": "🌄", "names": ["sunrise over mountains", "morning", "sun", "nature"]},
        {"emoji": "🌇", "names": ["sunset", "evening", "city", "dusk"]},
        {"emoji": "🌉", "names": ["bridge at night", "travel", "city", "landmark"]},
        {"emoji": "🎠", "names": ["carousel horse", "carnival", "amusement park", "ride"]},
        {"emoji": "🎡", "names": ["ferris wheel", "carnival", "amusement park", "ride"]},
        {"emoji": "🎢", "names": ["roller coaster", "carnival", "amusement park", "ride"]},
        {"emoji": "🚂", "names": ["locomotive", "train", "steam", "travel"]},
        {"emoji": "🚃", "names": ["railway car", "train", "transit", "travel"]},
        {"emoji": "🚄", "names": ["high-speed train", "bullet train", "transit", "travel"]},
        # Activities and Objects
        {"emoji": "⚽", "names": ["soccer ball", "football", "sports", "match"]},
        {"emoji": "🏀", "names": ["basketball", "sports", "hoop", "ball"]},
        {"emoji": "🏈", "names": ["american football", "sports", "superbowl", "ball"]},
        {"emoji": "⚾", "names": ["baseball", "sports", "homerun", "ball"]},
        {"emoji": "🥎", "names": ["softball", "sports", "ball", "game"]},
        {"emoji": "🎾", "names": ["tennis", "sports", "racket", "ball"]},
        {"emoji": "🏐", "names": ["volleyball", "sports", "beach", "ball"]},
        {"emoji": "🏉", "names": ["rugby football", "sports", "scrum", "ball"]},
        {"emoji": "🥏", "names": ["flying disc", "frisbee", "ultimate", "sports"]},
        {"emoji": "🎱", "names": ["pool 8 ball", "billiards", "game", "snooker"]},
        {"emoji": "🪀", "names": ["yo-yo", "toy", "spin", "game"]},
        {"emoji": "🏓", "names": ["ping pong", "table tennis", "sports", "paddle"]},
        {"emoji": "🏸", "names": ["badminton", "sports", "shuttlecock", "racket"]},
        {"emoji": "🏒", "names": ["ice hockey", "sports", "puck", "stick"]},
        {"emoji": "🏑", "names": ["field hockey", "sports", "ball", "stick"]},
        {"emoji": "🥍", "names": ["lacrosse", "sports", "crosse", "stick"]},
        {"emoji": "🏹", "names": ["bow and arrow", "archery", "sports", "target"]},
        {"emoji": "🎣", "names": ["fishing pole", "fish", "hobby", "outdoor"]},
        {"emoji": "🤿", "names": ["diving mask", "snorkeling", "ocean", "swim"]},
        {"emoji": "🥊", "names": ["boxing glove", "fight", "mma", "sports"]},
        {"emoji": "🥋", "names": ["martial arts uniform", "karate", "judo", "taekwondo"]},
        {"emoji": "🥅", "names": ["goal net", "soccer", "hockey", "sports"]},
        {"emoji": "⛳", "names": ["flag in hole", "golf", "sports", "green"]},
        {"emoji": "⛸️", "names": ["ice skate", "skating", "winter", "sports"]},
        {"emoji": "🥌", "names": ["curling stone", "winter sports", "ice", "match"]},
        {"emoji": "🎯", "names": ["bullseye", "target", "goal", "focus"]},
        {"emoji": "🪃", "names": ["boomerang", "australia", "throw", "toy"]},
        {"emoji": "🪁", "names": ["kite", "fly", "wind", "toy"]},
        {"emoji": "🔮", "names": ["crystal ball", "fortune", "magic", "future"]},
        {"emoji": "🪄", "names": ["magic wand", "wizard", "spell", "witch"]},
        {"emoji": "🎮", "names": ["video game", "controller", "gaming", "play"]},
        {"emoji": "🕹️", "names": ["joystick", "gaming", "arcade", "retro"]},
        {"emoji": "🎰", "names": ["slot machine", "casino", "gambling", "luck"]},
        {"emoji": "🎲", "names": ["game die", "dice", "board game", "gamble"]},
        {"emoji": "🧩", "names": ["puzzle piece", "jigsaw", "problem", "solve"]},
        {"emoji": "🧸", "names": ["teddy bear", "toy", "cute", "plush"]},
        {"emoji": "🪅", "names": ["piñata", "party", "celebration", "candy"]},
        {"emoji": "🪩", "names": ["mirror ball", "disco", "party", "dance"]},
        {"emoji": "🪆", "names": ["nesting dolls", "matryoshka", "russian", "toy"]},
        {"emoji": "♠️", "names": ["spade suit", "cards", "poker", "gambling"]},
        {"emoji": "♥️", "names": ["heart suit", "cards", "poker", "gambling"]},
        {"emoji": "♦️", "names": ["diamond suit", "cards", "poker", "gambling"]},
        {"emoji": "♣️", "names": ["club suit", "cards", "poker", "gambling"]},
        {"emoji": "♟️", "names": ["chess pawn", "board game", "strategy", "chess"]},
        {"emoji": "🎭", "names": ["performing arts", "theater", "drama", "masks"]},
        {"emoji": "🎨", "names": ["artist palette", "paint", "art", "design"]},
        {"emoji": "🧵", "names": ["thread", "sewing", "needle", "craft"]},
        {"emoji": "🪡", "names": ["sewing needle", "stitch", "tailor", "craft"]},
        {"emoji": "🧶", "names": ["yarn", "knitting", "wool", "craft"]},
        {"emoji": "🪢", "names": ["knot", "tie", "rope", "tangle"]},
        {"emoji": "👑", "names": ["crown", "royal", "king", "queen"]},
        {"emoji": "🎒", "names": ["backpack", "school", "bag", "travel"]},
        {"emoji": "👓", "names": ["glasses", "spectacles", "eyewear", "smart"]},
        {"emoji": "🕶️", "names": ["sunglasses", "cool", "eyewear", "summer"]},
        {"emoji": "🥽", "names": ["goggles", "safety", "science", "swim"]},
        {"emoji": "🥼", "names": ["lab coat", "science", "doctor", "chemist"]},
        {"emoji": "🦺", "names": ["safety vest", "construction", "caution", "neon"]},
        {"emoji": "👔", "names": ["necktie", "suit", "business", "formal"]},
        {"emoji": "👕", "names": ["t-shirt", "clothing", "shirt", "casual"]},
        {"emoji": "👖", "names": ["jeans", "pants", "clothing", "denim"]},
        {"emoji": "🧣", "names": ["scarf", "winter", "clothing", "cold"]},
        {"emoji": "🧤", "names": ["gloves", "winter", "clothing", "cold"]},
        {"emoji": "🧥", "names": ["coat", "jacket", "clothing", "winter"]},
        {"emoji": "🧦", "names": ["socks", "clothing", "feet", "warm"]},
        {"emoji": "👗", "names": ["dress", "clothing", "fashion", "female"]},
        {"emoji": "👘", "names": ["kimono", "japanese", "clothing", "traditional"]},
        {"emoji": "🥻", "names": ["sari", "indian", "clothing", "traditional"]},
        {"emoji": "🩱", "names": ["one-piece swimsuit", "swim", "pool", "beach"]},
        {"emoji": "🩲", "names": ["briefs", "underwear", "clothing", "swimsuit"]},
        {"emoji": "🩳", "names": ["shorts", "clothing", "casual", "summer"]},
        {"emoji": "💄", "names": ["lipstick", "makeup", "beauty", "cosmetics"]},
        {"emoji": "💍", "names": ["ring", "diamond", "jewelry", "marriage"]},
        {"emoji": "💼", "names": ["briefcase", "business", "work", "office"]},
        {"emoji": "🩸", "names": ["drop of blood", "medical", "injury", "donation"]},
        {"emoji": "🩹", "names": ["adhesive bandage", "hurt", "injury", "medical"]},
        {"emoji": "🩺", "names": ["stethoscope", "doctor", "medical", "hospital"]},
        {"emoji": "💊", "names": ["pill", "medicine", "drug", "tablet"]},
        {"emoji": "💉", "names": ["syringe", "injection", "vaccine", "medical"]},
        {"emoji": "🧼", "names": ["soap", "clean", "wash", "bathroom"]},
        {"emoji": "🪥", "names": ["toothbrush", "clean", "teeth", "hygiene"]},
        {"emoji": "🧽", "names": ["sponge", "clean", "wash", "kitchen"]},
        {"emoji": "🪠", "names": ["plunger", "toilet", "repair", "plumbing"]},
        {"emoji": "🧺", "names": ["basket", "laundry", "picnic", "storage"]},
        {"emoji": "🧻", "names": ["roll of paper", "toilet paper", "tissue", "bathroom"]},
        {"emoji": "🪞", "names": ["mirror", "reflection", "glass", "vanity"]},
        {"emoji": "🧴", "names": ["lotion bottle", "skincare", "cream", "sunscreen"]},
        {"emoji": "🪒", "names": ["razor", "shave", "barber", "grooming"]},
        {"emoji": "🧼", "names": ["soap", "clean", "wash", "bathroom"]},
        {"emoji": "🛒", "names": ["shopping cart", "grocery", "store", "buy"]},
        {"emoji": "🚬", "names": ["cigarette", "smoking", "tobacco", "smoke"]},
        {"emoji": "⚗️", "names": ["alembic", "science", "chemistry", "lab"]},
        {"emoji": "🔭", "names": ["telescope", "space", "stars", "astronomy"]},
        {"emoji": "🔬", "names": ["microscope", "science", "lab", "biology"]},
        {"emoji": "🪓", "names": ["axe", "tool", "wood", "chop"]},
        {"emoji": "🔨", "names": ["hammer", "tool", "repair", "build"]},
        {"emoji": "⚒️", "names": ["hammer and pick", "tools", "mining", "repair"]},
        {"emoji": "🛠️", "names": ["hammer and wrench", "tools", "repair", "build"]},
        {"emoji": "⛏️", "names": ["pick", "tool", "mining", "dig"]},
        {"emoji": "🪚", "names": ["hand saw", "tool", "wood", "carpentry"]},
        {"emoji": "🔧", "names": ["wrench", "tool", "repair", "spanner"]},
        {"emoji": "🪛", "names": ["screwdriver", "tool", "repair", "fix"]},
        {"emoji": "🔩", "names": ["nut and bolt", "hardware", "tool", "metal"]},
        {"emoji": "⚙️", "names": ["gear", "cog", "machinery", "settings"]},
        {"emoji": "🪤", "names": ["mouse trap", "catch", "pest", "trap"]},
        {"emoji": "🧱", "names": ["brick", "wall", "build", "construction"]},
        {"emoji": "⛓️", "names": ["chains", "metal", "lock", "link"]},
        {"emoji": "🧲", "names": ["magnet", "attract", "science", "physics"]},
        {"emoji": "🔫", "names": ["water pistol", "squirt gun", "toy", "summer"]},
        {"emoji": "💣", "names": ["bomb", "explode", "weapon", "danger"]},
        {"emoji": "🧨", "names": ["firecracker", "new year", "celebration", "explode"]},
        {"emoji": "🪓", "names": ["axe", "tool", "lumberjack", "chop"]},
        {"emoji": "🔪", "names": ["kitchen knife", "cooking", "chef", "slice"]},
        {"emoji": "🗡️", "names": ["dagger", "weapon", "sword", "blade"]},
        {"emoji": "⚔️", "names": ["crossed swords", "fight", "battle", "war"]},
        {"emoji": "🛡️", "names": ["shield", "protection", "armor", "defense"]},
        {"emoji": "🗝️", "names": ["old key", "secret", "unlock", "vintage"]},
        {"emoji": "🔑", "names": ["key", "unlock", "lock", "password"]},
        {"emoji": "🔒", "names": ["locked", "security", "privacy", "closed"]},
        {"emoji": "🔓", "names": ["unlocked", "security", "open", "privacy"]},
        {"emoji": "🔏", "names": ["locked with pen", "privacy", "sign", "security"]},
        {"emoji": "🔐", "names": ["locked with key", "security", "privacy", "closed"]},
        {"emoji": "🔑", "names": ["key", "unlock", "lock", "access"]},
        {"emoji": "🔔", "names": ["bell", "notification", "alert", "sound"]},
        {"emoji": "🔕", "names": ["bell with slash", "mute", "silent", "quiet"]},
        {"emoji": "📣", "names": ["megaphone", "announcement", "loud", "shout"]},
        {"emoji": "📢", "names": ["loudspeaker", "announcement", "broadcast", "volume"]},
        # Symbols
        {"emoji": "❤️", "names": ["red heart", "love", "like", "passion"]},
        {"emoji": "🧡", "names": ["orange heart", "love", "care", "warmth"]},
        {"emoji": "💛", "names": ["yellow heart", "love", "friendship", "kind"]},
        {"emoji": "💚", "names": ["green heart", "love", "envy", "jealous"]},
        {"emoji": "💙", "names": ["blue heart", "love", "trust", "peace"]},
        {"emoji": "💜", "names": ["purple heart", "love", "luxury", "royalty"]},
        {"emoji": "🖤", "names": ["black heart", "love", "dark", "goth"]},
        {"emoji": "🤍", "names": ["white heart", "love", "pure", "clean"]},
        {"emoji": "🤎", "names": ["brown heart", "love", "chocolate", "earth"]},
        {"emoji": "💔", "names": ["broken heart", "sad", "heartbreak", "divorce"]},
        {"emoji": "❤️‍🔥", "names": ["heart on fire", "passion", "love", "burning"]},
        {"emoji": "❤️‍🩹", "names": ["mending heart", "heal", "recovery", "better"]},
        {"emoji": "❣️", "names": ["heart exclamation", "love", "punctuation", "alert"]},
        {"emoji": "💕", "names": ["two hearts", "love", "romance", "sweet"]},
        {"emoji": "💞", "names": ["revolving hearts", "love", "romance", "crush"]},
        {"emoji": "💓", "names": ["beating heart", "love", "nervous", "pulse"]},
        {"emoji": "💗", "names": ["growing heart", "love", "crush", "excited"]},
        {"emoji": "💖", "names": ["sparkling heart", "love", "shiny", "cute"]},
        {"emoji": "💘", "names": ["heart with arrow", "cupid", "love", "valentine"]},
        {"emoji": "💝", "names": ["heart with ribbon", "gift", "present", "love"]},
        {"emoji": "💟", "names": ["heart decoration", "love", "frame", "purple"]},
        {"emoji": "☮️", "names": ["peace symbol", "peace", "hippie", "harmony"]},
        {"emoji": "✝️", "names": ["latin cross", "religion", "christian", "church"]},
        {"emoji": "☪️", "names": ["star and crescent", "religion", "islam", "mosque"]},
        {"emoji": "🕉️", "names": ["om", "religion", "hindu", "meditation"]},
        {"emoji": "☸️", "names": ["wheel of dharma", "religion", "buddhist", "meditation"]},
        {"emoji": "✡️", "names": ["star of david", "religion", "jewish", "synagogue"]},
        {"emoji": "🔯", "names": ["dotted six-pointed star", "religion", "mystical", "star"]},
        {"emoji": "🕎", "names": ["menorah", "religion", "jewish", "hanukkah"]},
        {"emoji": "☯️", "names": ["yin yang", "balance", "chinese", "philosophy"]},
        {"emoji": "☦️", "names": ["orthodox cross", "religion", "christian", "church"]},
        {"emoji": "🛐", "names": ["place of worship", "prayer", "religion", "church"]},
        {"emoji": "⛎", "names": ["ophiuchus", "zodiac", "astrology", "constellation"]},
        {"emoji": "♈", "names": ["aries", "zodiac", "astrology", "ram"]},
        {"emoji": "♉", "names": ["taurus", "zodiac", "astrology", "bull"]},
        {"emoji": "♊", "names": ["gemini", "zodiac", "astrology", "twins"]},
        {"emoji": "♋", "names": ["cancer", "zodiac", "astrology", "crab"]},
        {"emoji": "♌", "names": ["leo", "zodiac", "astrology", "lion"]},
        {"emoji": "♍", "names": ["virgo", "zodiac", "astrology", "maiden"]},
        {"emoji": "♎", "names": ["libra", "zodiac", "astrology", "scales"]},
        {"emoji": "♏", "names": ["scorpio", "zodiac", "astrology", "scorpion"]},
        {"emoji": "♐", "names": ["sagittarius", "zodiac", "astrology", "archer"]},
        {"emoji": "♑", "names": ["capricorn", "zodiac", "astrology", "goat"]},
        {"emoji": "♒", "names": ["aquarius", "zodiac", "astrology", "water"]},
        {"emoji": "♓", "names": ["pisces", "zodiac", "astrology", "fish"]},
        {"emoji": "🔀", "names": ["shuffle tracks button", "music", "random", "arrow"]},
        {"emoji": "🔁", "names": ["repeat button", "music", "loop", "arrow"]},
        {"emoji": "🔂", "names": ["repeat single button", "music", "loop", "once"]},
        {"emoji": "▶️", "names": ["play button", "media", "start", "video"]},
        {"emoji": "⏩", "names": ["fast-forward button", "media", "speed", "video"]},
        {"emoji": "⏭️", "names": ["next track button", "media", "skip", "music"]},
        {"emoji": "⏸️", "names": ["pause button", "media", "stop", "video"]},
        {"emoji": "⏹️", "names": ["stop button", "media", "end", "video"]},
        {"emoji": "◀️", "names": ["reverse button", "media", "back", "video"]},
        {"emoji": "⏪", "names": ["fast reverse button", "media", "rewind", "video"]},
        {"emoji": "⏮️", "names": ["last track button", "media", "back", "music"]},
        {"emoji": "🔼", "names": ["upwards button", "arrow", "triangle", "direction"]},
        {"emoji": "🔽", "names": ["downwards button", "arrow", "triangle", "direction"]},
        {"emoji": "⏫", "names": ["fast up button", "arrow", "direction", "speed"]},
        {"emoji": "⏬", "names": ["fast down button", "arrow", "direction", "speed"]},
        {"emoji": "➕", "names": ["plus", "math", "add", "sign"]},
        {"emoji": "➖", "names": ["minus", "math", "subtract", "sign"]},
        {"emoji": "✖️", "names": ["multiply", "math", "times", "sign"]},
        {"emoji": "➗", "names": ["divide", "math", "division", "sign"]},
        {"emoji": "🟰", "names": ["equals", "math", "equality", "sign"]},
        {"emoji": "♾️", "names": ["infinity", "forever", "endless", "math"]},
        {"emoji": "‼️", "names": ["double exclamation mark", "punctuation", "alert", "warning"]},
        {"emoji": "⁉️", "names": ["exclamation question mark", "punctuation", "confused", "shock"]},
        {"emoji": "❓", "names": ["question mark", "punctuation", "ask", "confused"]},
        {"emoji": "❔", "names": ["white question mark", "punctuation", "ask", "gray"]},
        {"emoji": "❕", "names": ["white exclamation mark", "punctuation", "alert", "gray"]},
        {"emoji": "❗", "names": ["exclamation mark", "punctuation", "alert", "warning"]},
        {"emoji": "〰️", "names": ["wavy dash", "punctuation", "wave", "line"]},
        {"emoji": "💱", "names": ["currency exchange", "money", "finance", "bank"]},
        {"emoji": "💲", "names": ["heavy dollar sign", "money", "cash", "finance"]},
        {"emoji": "♻️", "names": ["recycling symbol", "environment", "green", "eco"]},
        {"emoji": "⚜️", "names": ["fleur-de-lis", "royal", "france", "scout"]},
        {"emoji": "🔱", "names": ["trident emblem", "weapon", "poseidon", "anchor"]},
        {"emoji": "📛", "names": ["name badge", "school", "tag", "sticker"]},
        {"emoji": "🔰", "names": ["japanese symbol for beginner", "newbie", "rookie", "japan"]},
        {"emoji": "⭕", "names": ["heavy large circle", "correct", "yes", "circle"]},
        {"emoji": "✅", "names": ["check mark button", "correct", "done", "yes"]},
        {"emoji": "☑️", "names": ["check box with check", "correct", "done", "yes"]},
        {"emoji": "✔️", "names": ["check mark", "correct", "done", "yes"]},
        {"emoji": "❌", "names": ["cross mark", "wrong", "no", "delete"]},
        {"emoji": "❎", "names": ["cross mark button", "wrong", "no", "delete"]},
        {"emoji": "🔴", "names": ["red circle", "color", "round", "dot"]},
        {"emoji": "🔵", "names": ["blue circle", "color", "round", "dot"]},
        {"emoji": "⚫", "names": ["black circle", "color", "round", "dot"]},
        {"emoji": "⚪", "names": ["white circle", "color", "round", "dot"]},
        {"emoji": "⬛", "names": ["black large square", "color", "block", "shape"]},
        {"emoji": "⬜", "names": ["white large square", "color", "block", "shape"]},
        {"emoji": "🔶", "names": ["large orange diamond", "color", "shape", "gem"]},
        {"emoji": "🔷", "names": ["large blue diamond", "color", "shape", "gem"]},
        {"emoji": "🔸", "names": ["small orange diamond", "color", "shape", "gem"]},
        {"emoji": "🔹", "names": ["small blue diamond", "color", "shape", "gem"]},
        {"emoji": "🔺", "names": ["red triangle pointed up", "shape", "arrow", "direction"]},
        {"emoji": "🔻", "names": ["red triangle pointed down", "shape", "arrow", "direction"]},
        {"emoji": "💠", "names": ["diamond with a dot", "cute", "flower", "shape"]},
        {"emoji": "🔲", "names": ["black square button", "shape", "interface", "frame"]},
        {"emoji": "🔳", "names": ["white square button", "shape", "interface", "frame"]},
        {"emoji": "⚠️", "names": ["warning", "danger", "caution", "alert"]},
        {"emoji": "🚸", "names": ["children crossing", "school", "traffic", "caution"]},
        {"emoji": "⛔", "names": ["no entry", "forbidden", "stop", "traffic"]},
        {"emoji": "🚫", "names": ["prohibited", "forbidden", "no", "ban"]},
        {"emoji": "🚳", "names": ["no bicycles", "forbidden", "traffic", "bike"]},
        {"emoji": "🚭", "names": ["no smoking", "forbidden", "health", "smoke"]},
        {"emoji": "🚯", "names": ["no littering", "forbidden", "clean", "trash"]},
        {"emoji": "🚰", "names": ["potable water", "drink", "clean", "tap"]},
        {"emoji": "🚹", "names": ["men's room", "bathroom", "male", "sign"]},
        {"emoji": "🚺", "names": ["women's room", "bathroom", "female", "sign"]},
        {"emoji": "🚻", "names": ["restroom", "bathroom", "gender neutral", "sign"]},
        {"emoji": "🚼", "names": ["baby symbol", "changing room", "infant", "child"]},
        {"emoji": "🚾", "names": ["water closet", "bathroom", "toilet", "sign"]},
        {"emoji": "🛂", "names": ["passport control", "travel", "airport", "border"]},
        {"emoji": "🛃", "names": ["customs", "travel", "airport", "border"]},
        {"emoji": "🛄", "names": ["baggage claim", "travel", "airport", "luggage"]},
        {"emoji": "🛅", "names": ["left luggage", "travel", "airport", "storage"]},
        {"emoji": "⬆️", "names": ["up arrow", "direction", "north", "above"]},
        {"emoji": "↗️", "names": ["up-right arrow", "direction", "northeast", "diagonal"]},
        {"emoji": "➡️", "names": ["right arrow", "direction", "east", "next"]},
        # Flags
        {"emoji": "🏁", "names": ["chequered flag", "racing", "finish line", "sports"]},
        {"emoji": "🚩", "names": ["triangular flag", "post", "marker", "warning"]},
        {"emoji": "🎌", "names": ["crossed flags", "celebration", "japan", "holiday"]},
        {"emoji": "🏴", "names": ["black flag", "pirate", "goth", "anarchy"]},
        {"emoji": "🏳️", "names": ["white flag", "surrender", "peace", "truce"]},
        {"emoji": "🏳️‍🌈", "names": ["rainbow flag", "pride", "lgbt", "diversity"]},
        {"emoji": "🏳️‍⚧️", "names": ["transgender flag", "pride", "trans", "identity"]},
        {"emoji": "🏴‍☠️", "names": ["pirate flag", "skull", "crossbones", "sea"]},
        {"emoji": "🇺🇳", "names": ["united nations flag", "un", "global", "peace"]},
        {"emoji": "🇦🇫", "names": ["afghanistan flag", "country", "asia", "kabul"]},
        {"emoji": "🇦🇽", "names": ["åland islands flag", "territory", "europe", "mariehamn"]},
        {"emoji": "🇦🇱", "names": ["albania flag", "country", "europe", "tirana"]},
        {"emoji": "🇩🇿", "names": ["algeria flag", "country", "africa", "algiers"]},
        {"emoji": "🇦🇸", "names": ["american samoa flag", "territory", "oceania", "pago pago"]},
        {"emoji": "🇦🇩", "names": ["andorra flag", "country", "europe", "andorra la vella"]},
        {"emoji": "🇦🇴", "names": ["angola flag", "country", "africa", "luanda"]},
        {"emoji": "🇦🇮", "names": ["anguilla flag", "territory", "caribbean", "the valley"]},
        {"emoji": "🇦🇶", "names": ["antarctica flag", "continent", "south pole", "cold"]},
        {"emoji": "🇦🇬", "names": ["antigua & barbuda flag", "country", "caribbean", "st johns"]},
        {"emoji": "🇦🇷", "names": ["argentina flag", "country", "south america", "buenos aires"]},
        {"emoji": "🇦🇲", "names": ["armenia flag", "country", "asia", "yerevan"]},
        {"emoji": "🇦🇼", "names": ["aruba flag", "territory", "caribbean", "oranjestad"]},
        {"emoji": "🇦🇺", "names": ["australia flag", "country", "oceania", "canberra"]},
        {"emoji": "🇦🇹", "names": ["austria flag", "country", "europe", "vienna"]},
        {"emoji": "🇦🇿", "names": ["azerbaijan flag", "country", "asia", "baku"]},
        {"emoji": "🇧🇸", "names": ["bahamas flag", "country", "caribbean", "nassau"]},
        {"emoji": "🇧🇭", "names": ["bahrain flag", "country", "asia", "manama"]},
        {"emoji": "🇧🇩", "names": ["bangladesh flag", "country", "asia", "dhaka"]},
        {"emoji": "🇧🇧", "names": ["barbados flag", "country", "caribbean", "bridgetown"]},
        {"emoji": "🇧🇾", "names": ["belarus flag", "country", "europe", "minsk"]},
        {"emoji": "🇧🇪", "names": ["belgium flag", "country", "europe", "brussels"]},
        {"emoji": "🇧🇿", "names": ["belize flag", "country", "central america", "belmopan"]},
        {"emoji": "🇧🇯", "names": ["benin flag", "country", "africa", "porto-novo"]},
        {"emoji": "🇧🇲", "names": ["bermuda flag", "territory", "caribbean", "hamilton"]},
        {"emoji": "🇧🇹", "names": ["bhutan flag", "country", "asia", "thimphu"]},
        {"emoji": "🇧🇴", "names": ["bolivia flag", "country", "south america", "sucre"]},
        {"emoji": "🇧🇦", "names": ["bosnia & herzegovina flag", "country", "europe", "sarajevo"]},
        {"emoji": "🇧🇼", "names": ["botswana flag", "country", "africa", "gaborone"]},
        {"emoji": "🇧🇷", "names": ["brazil flag", "country", "south america", "brasilia"]},
        {"emoji": "🇻🇬", "names": ["british virgin islands flag", "territory", "caribbean", "road town"]},
        {"emoji": "🇧🇳", "names": ["brunei flag", "country", "asia", "bandar seri begawan"]},
        {"emoji": "🇧🇬", "names": ["bulgaria flag", "country", "europe", "sofia"]},
        {"emoji": "🇧🇫", "names": ["burkina faso flag", "country", "africa", "ouagadougou"]},
        {"emoji": "🇧🇮", "names": ["burundi flag", "country", "africa", "gitega"]},
        {"emoji": "🇰🇭", "names": ["cambodia flag", "country", "asia", "phnom penh"]},
        {"emoji": "🇨🇲", "names": ["cameroon flag", "country", "africa", "yaounde"]},
        {"emoji": "🇨🇦", "names": ["canada flag", "country", "north america", "ottawa"]},
        {"emoji": "🇨🇻", "names": ["cape verde flag", "country", "africa", "praia"]},
        {"emoji": "🇰🇾", "names": ["cayman islands flag", "territory", "caribbean", "george town"]},
        {"emoji": "🇨🇫", "names": ["central african republic flag", "country", "africa", "bangui"]},
        {"emoji": "🇹🇩", "names": ["chad flag", "country", "africa", "n'djamena"]},
        {"emoji": "🇨🇱", "names": ["chile flag", "country", "south america", "santiago"]},
        {"emoji": "🇨🇳", "names": ["china flag", "country", "asia", "beijing"]},
        {"emoji": "🇨🇴", "names": ["colombia flag", "country", "south america", "bogota"]},
        {"emoji": "🇰🇲", "names": ["comoros flag", "country", "africa", "moroni"]},
        {"emoji": "🇨🇬", "names": ["congo - brazzaville flag", "country", "africa", "brazzaville"]},
        {"emoji": "🇨🇩", "names": ["congo - kinshasa flag", "country", "africa", "kinshasa"]},
        {"emoji": "🇨🇰", "names": ["cook islands flag", "territory", "oceania", "avarua"]},
        {"emoji": "🇨🇷", "names": ["costa rica flag", "country", "central america", "san jose"]},
        {"emoji": "🇭🇷", "names": ["croatia flag", "country", "europe", "zagreb"]},
        {"emoji": "🇨🇺", "names": ["cuba flag", "country", "caribbean", "havana"]},
        {"emoji": "🇨🇼", "names": ["curaçao flag", "territory", "caribbean", "willemstad"]},
        {"emoji": "🇨🇾", "names": ["cyprus flag", "country", "europe", "nicosia"]},
        {"emoji": "🇨🇿", "names": ["czechia flag", "country", "europe", "prague"]},
        {"emoji": "🇩🇰", "names": ["denmark flag", "country", "europe", "copenhagen"]},
        {"emoji": "🇩🇯", "names": ["djibouti flag", "country", "africa", "djibouti"]},
        {"emoji": "🇩🇲", "names": ["dominica flag", "country", "caribbean", "roseau"]},
        {"emoji": "🇩🇴", "names": ["dominican republic flag", "country", "caribbean", "santo domingo"]},
        {"emoji": "🇪🇨", "names": ["ecuador flag", "country", "south america", "quito"]},
        {"emoji": "🇪🇬", "names": ["egypt flag", "country", "africa", "cairo"]},
        {"emoji": "🇸🇻", "names": ["el salvador flag", "country", "central america", "san salvador"]},
        {"emoji": "🇬🇶", "names": ["equatorial guinea flag", "country", "africa", "malabo"]},
        {"emoji": "🇪🇷", "names": ["eritrea flag", "country", "africa", "asmara"]},
        {"emoji": "🇪🇪", "names": ["estonia flag", "country", "europe", "tallinn"]},
        {"emoji": "🇸🇿", "names": ["eswatini flag", "country", "africa", "mbabane"]},
        {"emoji": "🇪🇹", "names": ["ethiopia flag", "country", "africa", "addis ababa"]},
        {"emoji": "🇫🇰", "names": ["falkland islands flag", "territory", "south america", "stanley"]},
        {"emoji": "🇫🇴", "names": ["faroe islands flag", "territory", "europe", "torshavn"]},
        {"emoji": "🇫🇯", "names": ["fiji flag", "country", "oceania", "suva"]},
        {"emoji": "🇫🇮", "names": ["finland flag", "country", "europe", "helsinki"]},
        {"emoji": "🇫🇷", "names": ["france flag", "country", "europe", "paris"]},
        {"emoji": "🇬🇫", "names": ["french guiana flag", "territory", "south america", "cayenne"]},
        {"emoji": "🇵🇫", "names": ["french polynesia flag", "territory", "oceania", "papeete"]},
        {"emoji": "🇬🇦", "names": ["gabon flag", "country", "africa", "libreville"]},
        {"emoji": "🇬🇲", "names": ["gambia flag", "country", "africa", "banjul"]},
        {"emoji": "🇬🇪", "names": ["georgia flag", "country", "asia", "tbilisi"]},
        {"emoji": "🇩🇪", "names": ["germany flag", "country", "europe", "berlin"]},
        {"emoji": "🇬🇭", "names": ["ghana flag", "country", "africa", "accra"]},
        {"emoji": "🇬🇮", "names": ["gibraltar flag", "territory", "europe", "gibraltar"]},
        {"emoji": "🇬🇷", "names": ["greece flag", "country", "europe", "athens"]},
        {"emoji": "🇬🇱", "names": ["greenland flag", "territory", "north america", "nuuk"]},
        {"emoji": "🇬🇩", "names": ["grenada flag", "country", "caribbean", "st george's"]},
        {"emoji": "🇬🇵", "names": ["guadeloupe flag", "territory", "caribbean", "basse-terre"]},
        {"emoji": "🇬🇺", "names": ["guam flag", "territory", "oceania", "hagåtña"]},
        {"emoji": "🇬🇹", "names": ["guatemala flag", "country", "central america", "guatemala city"]},
        {"emoji": "🇬🇬", "names": ["guernsey flag", "territory", "europe", "st peter port"]},
        {"emoji": "🇬🇳", "names": ["guinea flag", "country", "africa", "conakry"]},
        {"emoji": "🇬🇼", "names": ["guinea-bissau flag", "country", "africa", "bissau"]},
        {"emoji": "🇬🇾", "names": ["guyana flag", "country", "south america", "georgetown"]},
        {"emoji": "🇭🇹", "names": ["haiti flag", "country", "caribbean", "port-au-prince"]},
        {"emoji": "🇭🇳", "names": ["honduras flag", "country", "central america", "tegucigalpa"]},
        {"emoji": "🇭🇰", "names": ["hong kong flag", "territory", "asia", "hong kong"]},
        {"emoji": "🇭🇺", "names": ["hungary flag", "country", "europe", "budapest"]},
        {"emoji": "🇮🇸", "names": ["iceland flag", "country", "europe", "reykjavik"]},
        {"emoji": "🇮🇳", "names": ["india flag", "country", "asia", "new delhi"]},
        {"emoji": "🇮🇩", "names": ["indonesia flag", "country", "asia", "jakarta"]},
        {"emoji": "🇮🇷", "names": ["iran flag", "country", "asia", "tehran"]},
        {"emoji": "🇮🇶", "names": ["iraq flag", "country", "asia", "baghdad"]},
        {"emoji": "🇮🇪", "names": ["ireland flag", "country", "europe", "dublin"]},
        {"emoji": "🇮🇲", "names": ["isle of man flag", "territory", "europe", "douglas"]},
        {"emoji": "🇮🇱", "names": ["israel flag", "country", "asia", "jerusalem"]},
        ]

        # 3. Emoji Grid Layout (4 rows x 7 columns = 28 slots)
        self.grid_layout = QGridLayout()
        self.grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.populate_grid(self.all_emojis)
        container_layout.addLayout(self.grid_layout)

        main_layout.addWidget(self.container)

        # Connect search filter
        self.search_input.textChanged.connect(self.filter_emojis)

    def populate_grid(self, emoji_list):
        # Clear existing layout items safely
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)

        row, col = 0, 0
        for item in emoji_list:
            btn = QPushButton(item["emoji"])
            btn.setFixedSize(50, 48)
            btn.setFont(QFont("Apple Color Emoji", 30))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            
            btn.setStyleSheet("""
                QPushButton {
                    background-color: transparent; 
                    border-radius: 12px;
                    border: none;
                }
                QPushButton:hover {
                    background-color: rgba(255, 255, 255, 0.1);
                }
            """)
            btn.clicked.connect(lambda checked, e=item["emoji"]: self.on_emoji_clicked(e))
            
            self.grid_layout.addWidget(btn, row, col)
            col += 1
            if col >= 7:  # 7 columns per row
                col = 0
                row += 1
                if row >= 4:  # Max 4 rows at a glance
                    break

    def filter_emojis(self, text):
        query = text.lower().strip()
        if not query:
            self.populate_grid(self.all_emojis)
        else:
            # Filter emojis matching name/tags
            filtered = [
                item for item in self.all_emojis 
                if any(query in name for name in item["names"])
            ]
            self.populate_grid(filtered)

    def on_emoji_clicked(self, emoji):
        # 1. Emoji-ta clipboard-e copy kora
        try:
            p = subprocess.Popen(["wl-copy"], stdin=subprocess.PIPE, text=True)
            p.communicate(input=emoji)
        except Exception as e:
            print(f"Clipboard error: {e}")

        # 2. Window close NAA kore, direct background window-te Ctrl+V simulate kora
        try:
            subprocess.Popen(["bash", "-c", "sleep 0.05 && wtype -M ctrl -k v -m ctrl"])
        except Exception as e:
            print(f"Paste error: {e}")

    # Enable window dragging for floating window experience
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.oldPos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint() - self.oldPos
            self.move(self.pos() + delta)
            self.oldPos = event.globalPosition().toPoint()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

if __name__ == '__main__':
   # Hyprland Wayland Layer Formula
    QApplication.setDesktopFileName("hyprland-emoji-picker")
    
    app = QApplication(sys.argv)
    picker = EmojiPickerApp()
    picker.show()
    sys.exit(app.exec())