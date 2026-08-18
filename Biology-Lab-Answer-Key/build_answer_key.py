#!/usr/bin/env python3
"""Build a full worked-solution answer key PDF for ANTH 1 Lab Activity 2."""
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, HRFlowable, KeepTogether)
from reportlab.lib.enums import TA_LEFT

OUT = "/sessions/funny-amazing-thompson/mnt/outputs/Lab Activity 2 - Evolutionary Mechanisms - ANSWER KEY.pdf"

# ---- palette ----
INK      = colors.HexColor("#1f2933")
SLATE    = colors.HexColor("#334e68")
ACCENT   = colors.HexColor("#2b6cb0")   # blue for answers
BROWN    = colors.HexColor("#8a5a2b")
GREEN    = colors.HexColor("#2f855a")
BROWN_BG = colors.HexColor("#f3e9dd")
GREEN_BG = colors.HexColor("#e3f1e8")
HEADBG   = colors.HexColor("#334e68")
LIGHT    = colors.HexColor("#eef2f6")
RULE     = colors.HexColor("#c6d0da")

styles = getSampleStyleSheet()
def S(name, **kw):
    base = kw.pop("parent", styles["Normal"])
    return ParagraphStyle(name, parent=base, **kw)

title_st  = S("title", parent=styles["Title"], textColor=INK, fontSize=20, leading=24, spaceAfter=2)
sub_st    = S("sub", textColor=SLATE, fontSize=10.5, leading=14, alignment=TA_LEFT, spaceAfter=2)
meta_st   = S("meta", textColor=colors.HexColor("#627d98"), fontSize=8.5, leading=11)
intro_st  = S("intro", textColor=INK, fontSize=9.5, leading=13)
q_st      = S("q", textColor=INK, fontSize=10.5, leading=13, spaceBefore=4, spaceAfter=2, fontName="Helvetica-Bold")
qtext_st  = S("qtext", textColor=SLATE, fontSize=9.5, leading=12.5, spaceAfter=3)
ans_st    = S("ans", textColor=INK, fontSize=9.5, leading=13, leftIndent=10, spaceAfter=2)
ans_lbl   = S("anslbl", textColor=ACCENT, fontSize=9.5, leading=13, fontName="Helvetica-Bold")
work_st   = S("work", textColor=SLATE, fontSize=8.8, leading=12, leftIndent=10, spaceAfter=2)
sec_st    = S("sec", textColor=colors.white, fontSize=11, leading=14, fontName="Helvetica-Bold")
note_st   = S("note", textColor=colors.HexColor("#627d98"), fontSize=8.5, leading=11, spaceBefore=2)

story = []

def hr(c=RULE, w=0.8, sb=4, sa=6):
    story.append(Spacer(1, sb))
    story.append(HRFlowable(width="100%", thickness=w, color=c, spaceBefore=0, spaceAfter=0))
    story.append(Spacer(1, sa))

def section(label):
    t = Table([[Paragraph(label, sec_st)]], colWidths=[6.9*inch])
    t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),HEADBG),
                            ("LEFTPADDING",(0,0),(-1,-1),8),
                            ("TOPPADDING",(0,0),(-1,-1),4),
                            ("BOTTOMPADDING",(0,0),(-1,-1),4)]))
    story.append(Spacer(1,6)); story.append(t); story.append(Spacer(1,5))

def q(num, pts, qtext, answer_flowables):
    head = Paragraph(f'Question {num} <font color="#9aa5b1">({pts})</font>', q_st)
    blk = [head, Paragraph(qtext, qtext_st)] + answer_flowables
    story.append(KeepTogether(blk))
    story.append(Spacer(1,3))

def ans(text):
    return Paragraph(f'<font color="#2b6cb0"><b>Answer.</b></font> {text}', ans_st)

def work(text):
    return Paragraph(text, work_st)

# ---------------- HEADER ----------------
story.append(Paragraph("Answer Key &mdash; Lab Activity 2: Evolutionary Mechanisms", title_st))
story.append(Paragraph("ANTH 1 &middot; Natural Selection in a Population of Ants &middot; Full Worked Solutions", sub_st))
story.append(Paragraph("18 questions &middot; 50 points total. Frequencies rounded to the nearest thousandth. Each ant is assumed homozygous, so number of alleles = number of ants &times; 2.", meta_st))
hr(SLATE, 1.1, 6, 6)

# ---------------- SCENARIO ----------------
scenario = ("<b>Scenario in brief.</b> Ant color is controlled by one gene with two alleles "
            "(brown and green). An insect-eating primate hunts the ants by sight and eats the "
            "ones that are easiest to spot against the background. In the <b>rainy season</b> the "
            "trees hold green leaves, so the primate picks ants off green leaves; in the <b>dry "
            "season</b> the trees are bare, so the primate picks ants off brown branches. Whichever "
            "color blends in survives to reproduce, so allele frequencies shift across generations.")
story.append(Paragraph(scenario, intro_st))
hr()

# ---------------- SHORT ANSWER (Step setup) ----------------
section("Setup &amp; Hypothesis (Questions 1&ndash;5)")

q(1, "1 pt", "How do the ants vary?",
  [ans("They vary in <b>body color</b>: each ant is either brown or green. Color is set by a single "
       "gene with two alleles (brown and green), and we treat each ant as homozygous (two brown "
       "alleles = brown ant, two green alleles = green ant).")])

q(2, "1 pt", "What is the selective pressure?",
  [ans("<b>Predation by the primate.</b> The primate is the selective agent: it preferentially eats "
       "whichever ants are most visible against the current background, so an ant's color directly "
       "affects its chance of survival and reproduction.")])

q(3, "1 pt", "What is the dependent variable?",
  [ans("The <b>allele frequency</b> in the ant population (the frequency of the brown and green "
       "alleles). It is what we measure as it changes from generation to generation in response to "
       "selection.")])

q(4, "1 pt", "What is the independent variable?",
  [ans("The <b>season / environment</b> the primate hunts in &mdash; rainy season (green leaves) "
       "versus dry season (bare brown branches) &mdash; which sets the background color the ants are "
       "seen against. (Generation/time is the axis along which the change is tracked.)")])

q(5, "1 pt", "Write a hypothesis: during the rainy season, which allele frequency (brown or green) will increase over time?",
  [ans("The <b>green</b> allele frequency will increase."),
   work("<i>Sample hypothesis:</i> “If the primate hunts ants on green leaves during the rainy "
        "season, then the frequency of the green allele will increase over the generations, because "
        "green ants are camouflaged against the green background and are eaten less often than the "
        "more visible brown ants.”")])

# ---------------- TABLE HELPERS ----------------
def alleles_table(data):
    """data = list of 4 tuples (brown_alleles, green_alleles, total, brown_freq, green_freq)."""
    row_num   = ["Number of alleles"]
    row_tot   = ["Total # alleles\n(brown + green)"]
    row_freq  = ["Allele frequency"]
    row_tfreq = ["Total allele frequency\n(brown + green)"]
    for (ba, ga, tot, bf, gf) in data:
        row_num   += [ba, ga]
        row_tot   += [tot, ""]
        row_freq  += [bf, gf]
        row_tfreq += ["1.000", ""]
    header0 = ["", "Generation 1","","Generation 2","","Generation 3","","Generation 4",""]
    header1 = ["", "brown","green","brown","green","brown","green","brown","green"]
    rows = [header0, header1, row_num, row_tot, row_freq, row_tfreq]
    cw = [1.55*inch] + [0.668*inch]*8
    t = Table(rows, colWidths=cw)
    ts = [
        ("FONT",(0,0),(-1,-1),"Helvetica",8),
        ("FONT",(0,0),(-1,1),"Helvetica-Bold",8),
        ("FONT",(0,2),(0,-1),"Helvetica-Bold",7.5),
        ("TEXTCOLOR",(0,0),(-1,1),colors.white),
        ("BACKGROUND",(0,0),(-1,1),HEADBG),
        ("ALIGN",(1,0),(-1,-1),"CENTER"),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("GRID",(0,0),(-1,-1),0.5,RULE),
        ("BOX",(0,0),(-1,-1),1,SLATE),
        ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),
        ("LEFTPADDING",(0,0),(-1,-1),3),("RIGHTPADDING",(0,0),(-1,-1),3),
        # span generation headers
        ("SPAN",(1,0),(2,0)),("SPAN",(3,0),(4,0)),("SPAN",(5,0),(6,0)),("SPAN",(7,0),(8,0)),
        ("SPAN",(0,0),(0,1)),
        # span totals rows (row idx 3 and 5)
        ("SPAN",(1,3),(2,3)),("SPAN",(3,3),(4,3)),("SPAN",(5,3),(6,3)),("SPAN",(7,3),(8,3)),
        ("SPAN",(1,5),(2,5)),("SPAN",(3,5),(4,5)),("SPAN",(5,5),(6,5)),("SPAN",(7,5),(8,5)),
        ("TEXTCOLOR",(0,2),(0,-1),INK),
    ]
    # shade brown/green columns lightly on the data rows
    for col in (1,3,5,7):
        ts.append(("BACKGROUND",(col,2),(col,2),BROWN_BG))
        ts.append(("BACKGROUND",(col,4),(col,4),BROWN_BG))
    for col in (2,4,6,8):
        ts.append(("BACKGROUND",(col,2),(col,2),GREEN_BG))
        ts.append(("BACKGROUND",(col,4),(col,4),GREEN_BG))
    # alternate label shading
    ts.append(("BACKGROUND",(0,2),(0,-1),LIGHT))
    t.setStyle(TableStyle(ts))
    return t

def source_table(title, rows):
    header = ["", "brown ants", "green ants", "total ants"]
    data = [header] + rows
    t = Table(data, colWidths=[1.3*inch,1.1*inch,1.1*inch,1.1*inch])
    t.setStyle(TableStyle([
        ("FONT",(0,0),(-1,-1),"Helvetica",8.5),
        ("FONT",(0,0),(-1,0),"Helvetica-Bold",8.5),
        ("FONT",(0,1),(0,-1),"Helvetica-Bold",8.5),
        ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#52606d")),
        ("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("ALIGN",(1,0),(-1,-1),"CENTER"),
        ("GRID",(0,0),(-1,-1),0.5,RULE),
        ("TOPPADDING",(0,0),(-1,-1),2.5),("BOTTOMPADDING",(0,0),(-1,-1),2.5),
    ]))
    cap = Paragraph(title, S("cap", textColor=SLATE, fontSize=8.5, fontName="Helvetica-Bold", spaceAfter=2))
    return [cap, t]

# ---------------- RAINY SEASON ----------------
section("Rainy Season &mdash; Table 2 &amp; Questions 6&ndash;10")

story += source_table("Table 1 (given). Number of ants collected during the rainy season.",
    [["Generation 1","100","100","200"],
     ["Generation 2","90","120","210"],
     ["Generation 3","75","150","225"],
     ["Generation 4","65","170","235"]])
story.append(Spacer(1,5))
story.append(Paragraph("<b>Method.</b> alleles = ants &times; 2; total = brown + green alleles; "
                       "frequency = (color alleles) &divide; (total alleles), rounded to thousandths. "
                       "<i>e.g.</i> Gen 2 green = (120&times;2) &divide; (180+240) = 240 &divide; 420 = "
                       "<b>0.571</b>.", work_st))
story.append(Spacer(1,5))
story.append(Paragraph('<font color="#2b6cb0"><b>Question 6 (12 pts) &mdash; Table 2: Allele frequencies in the rainy season</b></font>', q_st))
rainy = [(200,200,400,"0.500","0.500"),
         (180,240,420,"0.429","0.571"),
         (150,300,450,"0.333","0.667"),
         (130,340,470,"0.277","0.723")]
story.append(alleles_table(rainy))
story.append(Spacer(1,6))

q(7, "2 pts", "What was the general trend (Gen 1 &rarr; Gen 4) of the <b>brown</b> allele frequency? Increase or decrease? Give the numbers.",
  [ans("<b>Decreased.</b> Brown allele frequency fell each generation: "
       "0.500 (Gen 1) &rarr; 0.429 (Gen 2) &rarr; 0.333 (Gen 3) &rarr; 0.277 (Gen 4) &mdash; a drop of 0.223.")])

q(8, "2 pts", "What was the general trend (Gen 1 &rarr; Gen 4) of the <b>green</b> allele frequency? Increase or decrease? Give the numbers.",
  [ans("<b>Increased.</b> Green allele frequency rose each generation: "
       "0.500 (Gen 1) &rarr; 0.571 (Gen 2) &rarr; 0.667 (Gen 3) &rarr; 0.723 (Gen 4) &mdash; a gain of 0.223.")])

q(9, "2 pts", "Was your hypothesis in Question 5 supported? Explain why or why not.",
  [ans("<b>Yes.</b> Question 5 predicted the green allele would increase in the rainy season, and it "
       "did &mdash; rising from 0.500 to 0.723 while brown fell from 0.500 to 0.277. On green leaves the "
       "green ants were camouflaged, so the primate ate proportionally more brown ants, and the green "
       "allele became more common over the four generations.")])

q(10, "2 pts", "During the dry season the trees lose their leaves and the primate eats ants off the brown branches. Which allele frequency (brown or green) do you hypothesize will increase?",
  [ans("The <b>brown</b> allele frequency will increase."),
   work("<i>Reasoning:</i> against bare brown branches the brown ants are now camouflaged and the green "
        "ants stand out, so the primate eats more green ants and the brown allele should rise over the generations.")])

# ---------------- DRY SEASON ----------------
section("Dry Season &mdash; Table 4 &amp; Questions 11&ndash;14")

story += source_table("Table 3 (given). Number of ants collected during the dry season.",
    [["Generation 1","65","170","235"],
     ["Generation 2","90","150","240"],
     ["Generation 3","125","120","245"],
     ["Generation 4","150","100","250"]])
story.append(Spacer(1,6))
story.append(Paragraph('<font color="#2b6cb0"><b>Question 11 (12 pts) &mdash; Table 4: Allele frequencies in the dry season</b></font>', q_st))
dry = [(130,340,470,"0.277","0.723"),
       (180,300,480,"0.375","0.625"),
       (250,240,490,"0.510","0.490"),
       (300,200,500,"0.600","0.400")]
story.append(alleles_table(dry))
story.append(Spacer(1,6))

q(12, "2 pts", "What was the general trend (Gen 1 &rarr; Gen 4) of the <b>brown</b> allele frequency? Increase or decrease? Give the numbers.",
  [ans("<b>Increased.</b> Brown allele frequency rose each generation: "
       "0.277 (Gen 1) &rarr; 0.375 (Gen 2) &rarr; 0.510 (Gen 3) &rarr; 0.600 (Gen 4) &mdash; a gain of 0.323.")])

q(13, "2 pts", "What was the general trend (Gen 1 &rarr; Gen 4) of the <b>green</b> allele frequency? Increase or decrease? Give the numbers.",
  [ans("<b>Decreased.</b> Green allele frequency fell each generation: "
       "0.723 (Gen 1) &rarr; 0.625 (Gen 2) &rarr; 0.490 (Gen 3) &rarr; 0.400 (Gen 4) &mdash; a drop of 0.323.")])

q(14, "2 pts", "Was your hypothesis at the beginning of Step Three (Question 10) supported? Explain why or why not.",
  [ans("<b>Yes.</b> Question 10 predicted the brown allele would increase in the dry season, and it did "
       "&mdash; rising from 0.277 to 0.600 while green fell from 0.723 to 0.400. On bare brown branches the "
       "brown ants were camouflaged, so the primate ate proportionally more green ants and the brown "
       "allele became more common.")])

# ---------------- SUMMARY ----------------
section("Summary Questions (15&ndash;18)")

q(15, "2 pts", "How did the ants vary &mdash; what is the main difference between them? Why is variation necessary for natural selection to work?",
  [ans("The ants varied in <b>color</b> (brown vs. green), a heritable trait set by one gene. Variation "
       "is necessary because natural selection acts on <b>differences in fitness among individuals</b>: "
       "selection can only favor one phenotype over another if more than one phenotype exists. If every "
       "ant were identical, predation would remove them at random, no allele would be favored, and allele "
       "frequencies could not shift in response to the environment.")])

q(16, "2 pts", "What is selective pressure? What was the selective pressure in this simulation?",
  [ans("A <b>selective pressure</b> is an environmental factor that affects survival and/or reproductive "
       "success, causing the alleles tied to favored phenotypes to change in frequency over time. In this "
       "simulation the selective pressure was <b>predation by the primate</b>, whose by-sight hunting "
       "favored whichever ant color was camouflaged against the current background.")])

q(17, "3 pts", "Natural selection produces a population better adapted to its environment. (A) What trait was adaptive in the rainy season? (B) What trait was adaptive in the dry season? (C) Are your answers the same or different, and what does that tell you?",
  [ans("<b>(A)</b> Rainy season: <b>green</b> coloration (camouflage on green leaves)."),
   Paragraph('<font color="#2b6cb0"><b></b></font>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<b>(B)</b> Dry season: <b>brown</b> coloration (camouflage on bare brown branches).', ans_st),
   Paragraph('&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<b>(C)</b> They are <b>different</b>. The advantageous '
             'trait depends on the environment &mdash; a phenotype that is beneficial in one setting can be '
             'harmful in another. As the environment changes, the direction of selection reverses, so '
             '“fitness” is context-dependent (much like the light/dark peppered moths). Across '
             'alternating wet and dry seasons, this back-and-forth selection keeps <b>both</b> alleles in '
             'the population.', ans_st)])

q(18, "Optional &mdash; not graded", "What did you think about this lab?",
  [Paragraph('<i>Optional reflection (ungraded) &mdash; edit freely.</i> This lab made the logic of natural '
             'selection concrete: by tracking real allele-frequency numbers across generations, I could see '
             'how a single selective pressure (predation) shifts a population, and how the same trait can be '
             'an advantage in one season and a disadvantage in the next.', work_st)])

hr(SLATE, 1.0, 8, 4)
story.append(Paragraph("All allele-frequency values were computed and checked programmatically; "
                       "every generation&rsquo;s brown + green frequencies sum to 1.000.", note_st))

doc = SimpleDocTemplate(OUT, pagesize=letter,
                        leftMargin=0.6*inch, rightMargin=0.6*inch,
                        topMargin=0.55*inch, bottomMargin=0.55*inch,
                        title="Lab Activity 2 - Evolutionary Mechanisms - Answer Key",
                        author="ANTH 1")
doc.build(story)
print("WROTE", OUT)
