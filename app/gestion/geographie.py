"""Géographie de référence pour le globe 3D.

Petite base embarquée (hors-ligne) qui associe un « pays » / une « ville »
(écrits librement dans l'application ou reçus d'un connecteur) à des
coordonnées latitude/longitude.

- :data:`PAYS_PAR_NOM` : centroid + ISO-2 + centre-ville (capitale) par pays.
- :func:`resoudre` retourne ``(lat, lng, iso2, nom_pays)`` ou ``None``.

Les coordonnées sont indicatives (positionnement d'agrégats), pas un
géo-codeur exact. Un connecteur qui fournit lui-même lat/lng n'a pas besoin
de ce module.
"""

import unicodedata

#: (lat, lng, iso2, lat_ville, lng_ville) — centroid + « ville de référence ».
PAYS_PAR_NOM = {
    "afghanistan": (33.9, 67.7, "af", 34.53, 69.17),
    "afrique du sud": (-30.6, 22.9, "za", -25.75, 28.19),
    "albanie": (41.15, 20.17, "al", 41.33, 19.82),
    "algerie": (28.0, 1.66, "dz", 36.75, 3.06),
    "allemagne": (51.16, 10.45, "de", 52.52, 13.40),
    "andorre": (42.51, 1.52, "ad", 42.51, 1.52),
    "angola": (-11.2, 17.87, "ao", -8.84, 13.23),
    "antigua et barbuda": (17.06, -61.80, "ag", 17.12, -61.85),
    "arabie saoudite": (23.89, 45.08, "sa", 24.71, 46.68),
    "argentine": (-38.42, -63.62, "ar", -34.60, -58.38),
    "armenie": (40.07, 45.04, "am", 40.18, 44.51),
    "australie": (-25.27, 133.78, "au", -35.28, 149.13),
    "autriche": (47.52, 14.55, "at", 48.21, 16.37),
    "azerbaidjan": (40.14, 47.58, "az", 40.41, 49.87),
    "bahamas": (25.03, -77.40, "bs", 25.06, -77.35),
    "bahrein": (25.93, 50.64, "bh", 26.23, 50.59),
    "bangladesh": (23.68, 90.36, "bd", 23.81, 90.41),
    "barbade": (13.19, -59.54, "bb", 13.10, -59.62),
    "belgique": (50.50, 4.47, "be", 50.85, 4.35),
    "belize": (17.19, -88.50, "bz", 17.25, -88.77),
    "benin": (9.31, 2.31, "bj", 6.37, 2.43),
    "bhoutan": (27.51, 90.43, "bt", 27.47, 89.64),
    "biélorussie": (53.71, 27.95, "by", 53.90, 27.57),
    "bielorussie": (53.71, 27.95, "by", 53.90, 27.57),
    "bolivie": (-16.29, -63.59, "bo", -16.50, -68.15),
    "bosnie-herzegovine": (43.92, 17.68, "ba", 43.86, 18.41),
    "botswana": (-22.33, 24.68, "bw", -24.65, 25.91),
    "bresil": (-14.24, -51.93, "br", -15.79, -47.88),
    "brunei": (4.54, 114.73, "bn", 4.90, 114.94),
    "bulgarie": (42.73, 25.49, "bg", 42.70, 23.32),
    "burkina faso": (12.24, -1.56, "bf", 12.37, -1.52),
    "burundi": (-3.37, 29.92, "bi", -3.38, 29.36),
    "cambodge": (12.57, 104.99, "kh", 11.56, 104.92),
    "cameroun": (7.37, 12.35, "cm", 3.87, 11.52),
    "canada": (56.13, -106.35, "ca", 45.42, -75.70),
    "cap-vert": (16.00, -24.01, "cv", 14.93, -23.51),
    "cap vert": (16.00, -24.01, "cv", 14.93, -23.51),
    "chili": (-35.68, -71.54, "cl", -33.45, -70.67),
    "chine": (35.86, 104.20, "cn", 39.90, 116.41),
    "chypre": (35.13, 33.43, "cy", 35.17, 33.36),
    "colombie": (4.57, -74.30, "co", 4.71, -74.07),
    "comores": (-11.88, 43.87, "km", -11.70, 43.26),
    "congo": (-0.23, 15.83, "cg", -4.27, 15.28),
    "congo-brazzaville": (-0.23, 15.83, "cg", -4.27, 15.28),
    "rdc": (-4.04, 21.76, "cd", -4.44, 15.27),
    "republique democratique du congo": (-4.04, 21.76, "cd", -4.44, 15.27),
    "coree du nord": (40.34, 127.51, "kp", 39.03, 125.75),
    "coree du sud": (35.91, 127.77, "kr", 37.57, 126.98),
    "costa rica": (9.75, -83.75, "cr", 9.93, -84.08),
    "cote d'ivoire": (7.54, -5.55, "ci", 6.83, -5.29),
    "cote d ivoire": (7.54, -5.55, "ci", 6.83, -5.29),
    "croatie": (45.10, 15.20, "hr", 45.81, 15.98),
    "cuba": (21.52, -77.78, "cu", 23.11, -82.37),
    "danemark": (56.26, 9.50, "dk", 55.68, 12.57),
    "djibouti": (11.83, 42.59, "dj", 11.59, 43.15),
    "dominique": (15.41, -61.37, "dm", 15.30, -61.39),
    "egypte": (26.82, 30.80, "eg", 30.04, 31.24),
    "emirats arabes unis": (23.42, 53.85, "ae", 24.45, 54.38),
    "equateur": (-1.83, -78.18, "ec", -0.18, -78.47),
    "erythree": (15.18, 39.78, "er", 15.32, 38.93),
    "espagne": (40.46, -3.75, "es", 40.42, -3.70),
    "estonie": (58.60, 25.01, "ee", 59.44, 24.75),
    "etats-unis": (37.09, -95.71, "us", 38.90, -77.04),
    "etats unis": (37.09, -95.71, "us", 38.90, -77.04),
    "usa": (37.09, -95.71, "us", 38.90, -77.04),
    "ethiopie": (9.15, 40.49, "et", 8.98, 38.76),
    "fidji": (-17.71, 178.07, "fj", -18.14, 178.44),
    "finlande": (61.92, 25.75, "fi", 60.17, 24.94),
    "france": (46.60, 2.21, "fr", 48.85, 2.35),
    "gabon": (-0.80, 11.61, "ga", 0.39, 9.45),
    "gambie": (13.44, -15.31, "gm", 13.45, -16.58),
    "georgie": (42.32, 43.36, "ge", 41.72, 44.83),
    "ghana": (7.95, -1.02, "gh", 5.60, -0.19),
    "grece": (39.07, 21.82, "gr", 37.98, 23.73),
    "grenade": (12.26, -61.60, "gd", 12.11, -61.68),
    "guatemala": (15.78, -90.23, "gt", 14.63, -90.51),
    "guinee": (9.95, -9.70, "gn", 9.51, -13.71),
    "guinee equatoriale": (1.65, 10.27, "gq", 3.75, 8.78),
    "guinee-bissau": (12.00, -15.00, "gw", 11.86, -15.60),
    "guyana": (4.86, -58.93, "gy", 6.80, -58.16),
    "haiti": (18.97, -72.29, "ht", 18.59, -72.31),
    "honduras": (15.20, -86.24, "hn", 14.07, -87.19),
    "hongrie": (47.16, 19.50, "hu", 47.50, 19.04),
    "inde": (20.59, 78.96, "in", 28.61, 77.21),
    "indonesie": (-0.79, 113.92, "id", -6.21, 106.85),
    "irak": (33.22, 43.68, "iq", 33.31, 44.36),
    "iran": (32.43, 53.69, "ir", 35.69, 51.39),
    "irlande": (53.14, -8.24, "ie", 53.35, -6.26),
    "islande": (64.96, -19.02, "is", 64.15, -21.94),
    "israel": (31.05, 34.85, "il", 31.77, 35.21),
    "italie": (41.87, 12.57, "it", 41.90, 12.50),
    "jamaique": (18.11, -77.30, "jm", 18.02, -76.81),
    "japon": (36.20, 138.25, "jp", 35.68, 139.69),
    "jordanie": (30.59, 36.24, "jo", 31.95, 35.93),
    "kazakhstan": (48.02, 66.92, "kz", 51.17, 71.45),
    "kenya": (-0.02, 37.91, "ke", -1.29, 36.82),
    "kirghizistan": (41.20, 74.77, "kg", 42.87, 74.59),
    "koweit": (29.31, 47.48, "kw", 29.38, 47.99),
    "laos": (19.86, 102.50, "la", 17.97, 102.63),
    "lesotho": (-29.61, 28.23, "ls", -29.31, 27.48),
    "lettonie": (56.88, 24.60, "lv", 56.95, 24.11),
    "liban": (33.85, 35.86, "lb", 33.89, 35.50),
    "liberia": (6.43, -9.43, "lr", 6.30, -10.80),
    "libye": (26.34, 17.23, "ly", 32.89, 13.19),
    "liechtenstein": (47.17, 9.56, "li", 47.14, 9.52),
    "lituanie": (55.17, 23.88, "lt", 54.69, 25.28),
    "luxembourg": (49.61, 6.13, "lu", 49.61, 6.13),
    "macedoine du nord": (41.61, 21.75, "mk", 41.99, 21.43),
    "madagascar": (-18.77, 46.87, "mg", -18.91, 47.53),
    "malaisie": (4.21, 101.98, "my", 3.14, 101.69),
    "malawi": (-13.25, 34.30, "mw", -13.97, 33.79),
    "maldives": (3.20, 73.22, "mv", 4.17, 73.51),
    "mali": (17.57, -3.99, "ml", 12.64, -8.00),
    "malte": (35.94, 14.38, "mt", 35.90, 14.51),
    "maroc": (31.79, -7.09, "ma", 34.02, -6.84),
    "marshall": (7.13, 171.18, "mh", 7.09, 171.38),
    "maurice": (-20.35, 57.55, "mu", -20.16, 57.50),
    "mauritanie": (21.01, -10.94, "mr", 18.07, -15.96),
    "mexique": (23.63, -102.55, "mx", 19.43, -99.13),
    "micronesie": (7.43, 150.55, "fm", 6.92, 158.16),
    "moldavie": (47.41, 28.37, "md", 47.01, 28.86),
    "monaco": (43.74, 7.42, "mc", 43.74, 7.42),
    "mongolie": (46.86, 103.85, "mn", 47.89, 106.91),
    "montenegro": (42.71, 19.37, "me", 42.44, 19.26),
    "mozambique": (-18.67, 35.53, "mz", -25.97, 32.57),
    "myanmar": (21.92, 95.96, "mm", 19.76, 96.08),
    "namibie": (-22.96, 18.49, "na", -22.56, 17.08),
    "nepal": (28.39, 84.12, "np", 27.72, 85.32),
    "nicaragua": (12.87, -85.21, "ni", 12.14, -86.25),
    "niger": (17.61, 8.08, "ne", 13.51, 2.13),
    "nigeria": (9.08, 8.68, "ng", 9.06, 7.49),
    "norvege": (60.47, 8.47, "no", 59.91, 10.75),
    "nouvelle-zelande": (-40.90, 174.89, "nz", -41.29, 174.78),
    "oman": (21.47, 55.98, "om", 23.59, 58.41),
    "ouganda": (1.37, 32.29, "ug", 0.35, 32.58),
    "ouzbekistan": (41.38, 64.59, "uz", 41.30, 69.24),
    "pakistan": (30.38, 69.35, "pk", 33.68, 73.05),
    "palestine": (31.95, 35.23, "ps", 31.90, 35.20),
    "panama": (8.54, -80.78, "pa", 8.99, -79.52),
    "papouasie-nouvelle-guinee": (-6.31, 143.96, "pg", -9.44, 147.18),
    "paraguay": (-23.44, -58.44, "py", -25.26, -57.58),
    "pays-bas": (52.13, 5.29, "nl", 52.37, 4.90),
    "pays bas": (52.13, 5.29, "nl", 52.37, 4.90),
    "perou": (-9.19, -75.02, "pe", -12.05, -77.04),
    "philippines": (12.88, 121.77, "ph", 14.60, 120.98),
    "pologne": (51.92, 19.15, "pl", 52.23, 21.01),
    "porto rico": (18.22, -66.59, "pr", 18.46, -66.11),
    "portugal": (39.40, -8.22, "pt", 38.72, -9.14),
    "qatar": (25.35, 51.18, "qa", 25.29, 51.53),
    "republique centrafricaine": (6.61, 20.94, "cf", 4.39, 18.56),
    "republique dominicaine": (18.74, -70.16, "do", 18.49, -69.93),
    "republique tcheque": (49.82, 15.47, "cz", 50.08, 14.44),
    "roumanie": (45.94, 24.97, "ro", 44.43, 26.10),
    "royaume-uni": (55.38, -3.44, "gb", 51.51, -0.13),
    "grande bretagne": (55.38, -3.44, "gb", 51.51, -0.13),
    "angleterre": (55.38, -3.44, "gb", 51.51, -0.13),
    "russie": (61.52, 105.32, "ru", 55.75, 37.62),
    "rwanda": (-1.94, 29.87, "rw", -1.94, 30.06),
    "saint-kitts": (17.36, -62.78, "kn", 17.30, -62.72),
    "sainte-lucie": (13.91, -60.97, "lc", 14.01, -60.99),
    "salvador": (13.79, -88.90, "sv", 13.69, -89.22),
    "samoa": (-13.76, -172.10, "ws", -13.83, -171.77),
    "sao tome": (0.19, 6.61, "st", 0.34, 6.73),
    "senegal": (14.50, -14.45, "sn", 14.72, -17.47),
    "serbie": (44.02, 21.01, "rs", 44.79, 20.45),
    "seychelles": (-4.68, 55.49, "sc", -4.62, 55.45),
    "sierra leone": (8.46, -11.78, "sl", 8.48, -13.23),
    "singapour": (1.35, 103.82, "sg", 1.35, 103.82),
    "slovaquie": (48.67, 19.70, "sk", 48.15, 17.11),
    "slovenie": (46.15, 14.99, "si", 46.05, 14.51),
    "somalie": (5.15, 46.20, "so", 2.03, 45.34),
    "soudan": (12.86, 30.22, "sd", 15.50, 32.56),
    "sri lanka": (7.87, 80.77, "lk", 6.93, 79.85),
    "suede": (60.13, 18.64, "se", 59.33, 18.06),
    "suisse": (46.82, 8.23, "ch", 46.95, 7.45),
    "suriname": (3.92, -56.03, "sr", 5.85, -55.20),
    "swaziland": (-26.52, 31.47, "sz", -26.32, 31.13),
    "syrie": (34.80, 39.00, "sy", 33.51, 36.29),
    "tadjikistan": (38.86, 71.28, "tj", 38.56, 68.78),
    "taiwan": (23.70, 120.96, "tw", 25.03, 121.57),
    "tanzanie": (-6.37, 34.89, "tz", -6.79, 39.21),
    "tchad": (15.45, 18.73, "td", 12.11, 15.04),
    "thailande": (15.87, 100.99, "th", 13.75, 100.50),
    "timor oriental": (-8.87, 125.73, "tl", -8.56, 125.57),
    "togo": (8.62, 0.82, "tg", 6.13, 1.22),
    "tonka": (-21.18, -175.20, "to", -21.14, -175.20),
    "trinite et tobago": (10.69, -61.22, "tt", 10.66, -61.52),
    "tunisie": (33.89, 9.54, "tn", 36.81, 10.18),
    "turkménistan": (38.97, 59.56, "tm", 37.94, 58.38),
    "turkmenistan": (38.97, 59.56, "tm", 37.94, 58.38),
    "turquie": (38.96, 35.24, "tr", 39.93, 32.86),
    "tuvalu": (-7.48, 178.68, "tv", -8.52, 179.20),
    "ukraine": (48.38, 31.17, "ua", 50.45, 30.52),
    "uruguay": (-32.52, -55.77, "uy", -34.90, -56.16),
    "vanuatu": (-15.38, 166.96, "vu", -17.73, 168.32),
    "vatican": (41.90, 12.45, "va", 41.90, 12.45),
    "venezuela": (6.42, -66.59, "ve", 10.48, -66.90),
    "vietnam": (14.06, 108.28, "vn", 21.03, 105.85),
    "yemen": (15.55, 48.52, "ye", 15.35, 44.21),
    "zambie": (-13.13, 27.85, "zm", -15.42, 28.28),
    "zimbabwe": (-19.02, 29.15, "zw", -17.83, 31.05),
}

#: Villes additionnelles clés (commerce), clés ``(pays_norm, ville_norm)``.
VILLES = {
    ("france", "paris"): (48.85, 2.35),
    ("france", "lyon"): (45.76, 4.84),
    ("france", "marseille"): (43.30, 5.37),
    ("france", "toulouse"): (43.60, 1.44),
    ("france", "bordeaux"): (44.84, -0.58),
    ("france", "lille"): (50.63, 3.06),
    ("france", "nantes"): (47.22, -1.55),
    ("france", "strasbourg"): (48.57, 7.75),
    ("france", "nice"): (43.70, 7.27),
    ("etats-unis", "new york"): (40.71, -74.01),
    ("etats-unis", "los angeles"): (34.05, -118.24),
    ("etats-unis", "chicago"): (41.88, -87.63),
    ("etats-unis", "houston"): (29.76, -95.37),
    ("etats-unis", "miami"): (25.76, -80.19),
    ("etats-unis", "san francisco"): (37.77, -122.42),
    ("canada", "montreal"): (45.50, -73.57),
    ("canada", "toronto"): (43.65, -79.38),
    ("canada", "vancouver"): (49.28, -123.12),
    ("mexique", "mexico"): (19.43, -99.13),
    ("bresil", "sao paulo"): (-23.55, -46.63),
    ("bresil", "rio de janeiro"): (-22.91, -43.17),
    ("argentine", "buenos aires"): (-34.60, -58.38),
    ("chili", "santiago"): (-33.45, -70.67),
    ("colombie", "bogota"): (4.71, -74.07),
    ("perou", "lima"): (-12.05, -77.04),
    ("venezuela", "caracas"): (10.48, -66.90),
    ("royaume-uni", "londres"): (51.51, -0.13),
    ("royaume-uni", "manchester"): (53.48, -2.24),
    ("royaume-uni", "birmingham"): (52.49, -1.89),
    ("irlande", "dublin"): (53.35, -6.26),
    ("belgique", "bruxelles"): (50.85, 4.35),
    ("pays-bas", "amsterdam"): (52.37, 4.90),
    ("pays-bas", "rotterdam"): (51.92, 4.48),
    ("allemagne", "berlin"): (52.52, 13.40),
    ("allemagne", "munich"): (48.14, 11.58),
    ("allemagne", "francfort"): (50.11, 8.68),
    ("allemagne", "hambourg"): (53.55, 9.99),
    ("allemagne", "cologne"): (50.94, 6.96),
    ("suisse", "geneve"): (46.20, 6.14),
    ("suisse", "zurich"): (47.37, 8.54),
    ("autriche", "vienne"): (48.21, 16.37),
    ("italie", "rome"): (41.90, 12.50),
    ("italie", "milan"): (45.46, 9.19),
    ("italie", "turin"): (45.07, 7.69),
    ("italie", "naples"): (40.85, 14.27),
    ("espagne", "madrid"): (40.42, -3.70),
    ("espagne", "barcelone"): (41.39, 2.17),
    ("espagne", "valence"): (39.47, -0.38),
    ("portugal", "lisbonne"): (38.72, -9.14),
    ("portugal", "porto"): (41.15, -8.61),
    ("grece", "athenes"): (37.98, 23.73),
    ("turquie", "istanbul"): (41.01, 28.98),
    ("turquie", "ankara"): (39.93, 32.86),
    ("inde", "mumbai"): (19.08, 72.88),
    ("inde", "delhi"): (28.61, 77.21),
    ("inde", "bangalore"): (12.97, 77.59),
    ("inde", "chennai"): (13.08, 80.27),
    ("inde", "kolkata"): (22.57, 88.36),
    ("chine", "shanghai"): (31.23, 121.47),
    ("chine", "shenzhen"): (22.54, 114.06),
    ("chine", "canton"): (23.13, 113.26),
    ("chine", "pekin"): (39.90, 116.41),
    ("japon", "tokyo"): (35.68, 139.69),
    ("japon", "osaka"): (34.69, 135.50),
    ("japon", "kyoto"): (35.01, 135.77),
    ("coree du sud", "seoul"): (37.57, 126.98),
    ("singapour", "singapour"): (1.35, 103.82),
    ("malaisie", "kuala lumpur"): (3.14, 101.69),
    ("indonesie", "jakarta"): (-6.21, 106.85),
    ("indonesie", "bali"): (-8.41, 115.19),
    ("thailande", "bangkok"): (13.75, 100.50),
    ("vietnam", "ho chi minh ville"): (10.82, 106.63),
    ("vietnam", "hanoi"): (21.03, 105.85),
    ("philippines", "manille"): (14.60, 120.98),
    ("australie", "sydney"): (-33.87, 151.21),
    ("australie", "melbourne"): (-37.81, 144.96),
    ("australie", "brisbane"): (-27.47, 153.03),
    ("nouvelle-zelande", "auckland"): (-36.85, 174.76),
    ("russie", "moscou"): (55.75, 37.62),
    ("russie", "saint-petersbourg"): (59.93, 30.36),
    ("russie", "novossibirsk"): (55.03, 82.92),
    ("pologne", "varsovie"): (52.23, 21.01),
    ("republique tcheque", "prague"): (50.08, 14.44),
    ("hongrie", "budapest"): (47.50, 19.04),
    ("roumanie", "bucarest"): (44.43, 26.10),
    ("bulgarie", "sofia"): (42.70, 23.32),
    ("serbie", "belgrade"): (44.79, 20.45),
    ("ukraine", "kyiv"): (50.45, 30.52),
    ("egypte", "le caire"): (30.04, 31.24),
    ("maroc", "casablanca"): (33.57, -7.59),
    ("algerie", "alger"): (36.75, 3.06),
    ("tunisie", "tunis"): (36.81, 10.18),
    ("senegal", "dakar"): (14.72, -17.47),
    ("cote d ivoire", "abidjan"): (5.36, -4.01),
    ("ghana", "accra"): (5.60, -0.19),
    ("nigeria", "lagos"): (6.45, 3.39),
    ("nigeria", "abuja"): (9.06, 7.49),
    ("cameroun", "douala"): (4.05, 9.70),
    ("congo-brazzaville", "brazzaville"): (-4.27, 15.28),
    ("congo-brazzaville", "pointe-noire"): (-4.78, 11.86),
    ("congo-brazzaville", "dolisie"): (-4.20, 12.67),
    ("congo-brazzaville", "nkayi"): (-4.18, 13.29),
    ("congo-brazzaville", "ouesso"): (1.61, 16.05),
    ("congo-brazzaville", "owando"): (-0.48, 15.90),
    ("congo-brazzaville", "impfondo"): (1.62, 18.06),
    ("congo-brazzaville", "madingou"): (-4.15, 13.55),
    ("congo-brazzaville", "sibiti"): (-3.68, 13.35),
    ("congo-brazzaville", "oyo"): (-1.16, 15.99),
    ("congo-brazzaville", "mossendjo"): (-2.95, 12.72),
    ("congo-brazzaville", "kinkala"): (-4.36, 14.76),
    ("congo-brazzaville", "djambala"): (-2.54, 14.75),
    ("congo-brazzaville", "ewo"): (-0.87, 14.82),
    ("rdc", "lubumbashi"): (-11.66, 27.48),
    ("rdc", "matadi"): (-5.82, 13.45),
    ("rdc", "goma"): (-1.68, 29.22),
    ("rdc", "kisangani"): (0.52, 25.19),
    ("rdc", "mbuji-mayi"): (-6.13, 23.59),
    ("gabon", "port-gentil"): (-0.72, 8.78),
    ("gabon", "franceville"): (-1.63, 13.58),
    ("cameroun", "yaounde"): (3.85, 11.50),
    ("angola", "luanda"): (-8.84, 13.23),
    ("rdc", "kinshasa"): (-4.44, 15.27),
    ("benin", "cotonou"): (6.37, 2.43),
    ("togo", "lome"): (6.13, 1.22),
    ("afrique du sud", "johannesburg"): (-26.20, 28.05),
    ("afrique du sud", "le cap"): (-33.92, 18.42),
    ("kenya", "nairobi"): (-1.29, 36.82),
    ("ethiopie", "addis-abeba"): (9.02, 38.75),
    ("ouganda", "kampala"): (0.35, 32.58),
    ("tanzanie", "dar es salaam"): (-6.79, 39.21),
    ("angola", "luanda"): (-8.84, 13.23),
    ("mozambique", "maputo"): (-25.97, 32.57),
    ("madagascar", "antananarivo"): (-18.91, 47.53),
    ("saoudite", "riyad"): (24.71, 46.68),
    ("emirats arabes unis", "dubai"): (25.20, 55.27),
    ("emirats arabes unis", "abou dabi"): (24.45, 54.38),
    ("qatar", "doha"): (25.29, 51.53),
    ("israel", "tel-aviv"): (32.08, 34.78),
    ("arabie saoudite", "riyad"): (24.71, 46.68),
    ("turkménistan", "achgabat"): (37.94, 58.38),
    ("kazakhstan", "almaty"): (43.24, 76.89),
}

ISO_PAR_NOM = {norm: (lat, lng, iso) for norm, (lat, lng, iso, *_) in PAYS_PAR_NOM.items()}

#: Codes ISO-2 → (lat, lng, iso, lat_ville, lng_ville) — pour les webhooks
#: qui envoient des codes pays (WooCommerce « FR », Shopify « FR »…).
PAYS_PAR_ISO = {v[2]: v for v in PAYS_PAR_NOM.values()}


def normaliser(texte):
    """Minuscules sans accents ni espaces multiples (pour les recherches)."""
    texte = unicodedata.normalize("NFKD", str(texte or ""))
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    return " ".join(texte.lower().split())


def _pays_pour_iso(code):
    """(lat, lng, iso2, nom_normalisé) pour un code ISO-2, sinon None."""
    norm = normaliser(code)
    if len(norm) != 2:
        return None
    valeurs = PAYS_PAR_ISO.get(norm.lower())
    if not valeurs:
        return None
    lat, lng, iso, *_ = valeurs
    nom = {v[2]: cle for cle, v in PAYS_PAR_NOM.items()}.get(iso, code)
    return lat, lng, iso, nom


def _pays_pour_texte(pays):
    """Retourne (lat, lng, iso2, nom_normalisé) si le pays est connu."""
    norm = normaliser(pays)
    if not norm:
        return None
    # Nom français canonique des listes déroulantes (« Viêt Nam », « Eswatini »…).
    iso_fr = _ISO_PAR_NOM_FR().get(norm)
    if iso_fr and iso_fr in PAYS_PAR_ISO:
        lat, lng, iso, *_ = PAYS_PAR_ISO[iso_fr]
        cle = next(k for k, v in PAYS_PAR_NOM.items() if v[2] == iso)
        return lat, lng, iso, cle
    for cle, valeurs in PAYS_PAR_NOM.items():
        if norm == cle:
            lat, lng, iso, *_ = valeurs
            return lat, lng, iso, cle
    for cle, valeurs in PAYS_PAR_NOM.items():
        if cle in norm:
            lat, lng, iso, *_ = valeurs
            return lat, lng, iso, cle
    # Dernier essai : pays fourni comme code ISO-2 (FR, BF, CG, US…).
    return _pays_pour_iso(pays)


def resoudre(pays, ville=""):
    """Résout pays (+ ville) en coordonnées.

    Retourne ``(latitude, longitude, iso2, nom_pays_normalise)`` ou ``None``.
    La ville est préférée si elle est connue ; sinon on retombe sur le
    centre du pays (centroid) ou sa ville de référence.
    """
    pays = (pays or "").strip()
    ville = (ville or "").strip()
    info = _pays_pour_texte(pays) if pays else None
    if info is None:
        # Pays absent ou inconnu : on tente de déduire le pays depuis la ville
        # (uniquement si le nom de ville est sans ambiguïté).
        return ville_seule(ville)

    lat, lng, iso, nom = info
    if ville:
        cible = normaliser(ville)
        for cle, coords in VILLES.items():
            # Comparaison par code ISO : « Congo » et « Congo-Brazzaville » sont le même pays.
            iso_ville = PAYS_PAR_NOM.get(cle[0], (None, None, None))[2]
            if iso_ville == iso and normaliser(cle[1]) == cible:
                return (coords[0], coords[1], iso, nom)
    _, _, _, lat_v, lng_v = PAYS_PAR_NOM[nom]
    if lat_v is not None:
        return (lat_v, lng_v, iso, nom)
    return (lat, lng, iso, nom)


def ville_seule(ville):
    """(lat, lng, iso2, nom_pays) d'après la ville seule, si elle est unique ; sinon None."""
    cible = normaliser(ville)
    if not cible:
        return None
    trouves = [(cle, c) for cle, c in VILLES.items() if normaliser(cle[1]) == cible]
    isos = {PAYS_PAR_NOM[cle[0]][2] for cle, _ in trouves if cle[0] in PAYS_PAR_NOM}
    if len(isos) != 1:
        return None
    (nom, _), coords = trouves[0]
    return (coords[0], coords[1], PAYS_PAR_NOM[nom][2], nom)


#: Libellés d'affichage pour les noms de pays normalisés ambigus.
NOMS_AFFICHES = {"congo-brazzaville": "Congo", "congo": "Congo", "rdc": "RD Congo"}


def nom_affiche(nom):
    """Nom de pays lisible à partir de sa clé normalisée (« benin » → « Bénin » si connu)."""
    if not nom:
        return ""
    if nom in NOMS_AFFICHES:
        return NOMS_AFFICHES[nom]
    iso = PAYS_PAR_NOM.get(nom, (None, None, None))[2]
    if iso and iso in globals().get("NOMS_FR", {}):
        return {"cg": "Congo", "cd": "RD Congo", "cf": "Centrafrique"}.get(iso, NOMS_FR[iso])
    return nom[:1].upper() + nom[1:]


def est_connu(pays):
    return _pays_pour_texte(pays) is not None

#: Nom français (avec accents) de chaque pays connu, par code ISO-2 — utilisé
#: pour les listes déroulantes (formulaires client / société).
NOMS_FR = {
    "ad": "Andorre", "ae": "Émirats arabes unis", "af": "Afghanistan", "ag": "Antigua-et-Barbuda",
    "al": "Albanie", "am": "Arménie", "ao": "Angola", "ar": "Argentine", "at": "Autriche",
    "au": "Australie", "az": "Azerbaïdjan", "ba": "Bosnie-Herzégovine", "bb": "Barbade",
    "bd": "Bangladesh", "be": "Belgique", "bf": "Burkina Faso", "bg": "Bulgarie", "bh": "Bahreïn",
    "bi": "Burundi", "bj": "Bénin", "bn": "Brunei", "bo": "Bolivie", "br": "Brésil", "bs": "Bahamas",
    "bt": "Bhoutan", "bw": "Botswana", "by": "Biélorussie", "bz": "Belize", "ca": "Canada",
    "cd": "République démocratique du Congo", "cf": "République centrafricaine",
    "cg": "Congo-Brazzaville", "ch": "Suisse", "ci": "Côte d'Ivoire", "cl": "Chili", "cm": "Cameroun",
    "cn": "Chine", "co": "Colombie", "cr": "Costa Rica", "cu": "Cuba", "cv": "Cap-Vert", "cy": "Chypre",
    "cz": "République tchèque", "de": "Allemagne", "dj": "Djibouti", "dk": "Danemark", "dm": "Dominique",
    "do": "République dominicaine", "dz": "Algérie", "ec": "Équateur", "ee": "Estonie", "eg": "Égypte",
    "er": "Érythrée", "es": "Espagne", "et": "Éthiopie", "fi": "Finlande", "fj": "Fidji",
    "fm": "Micronésie", "fr": "France", "ga": "Gabon", "gb": "Royaume-Uni", "gd": "Grenade",
    "ge": "Géorgie", "gh": "Ghana", "gm": "Gambie", "gn": "Guinée", "gq": "Guinée équatoriale",
    "gr": "Grèce", "gt": "Guatemala", "gw": "Guinée-Bissau", "gy": "Guyana", "hn": "Honduras",
    "hr": "Croatie", "ht": "Haïti", "hu": "Hongrie", "id": "Indonésie", "ie": "Irlande", "il": "Israël",
    "in": "Inde", "iq": "Irak", "ir": "Iran", "is": "Islande", "it": "Italie", "jm": "Jamaïque",
    "jo": "Jordanie", "jp": "Japon", "ke": "Kenya", "kg": "Kirghizistan", "kh": "Cambodge",
    "km": "Comores", "kn": "Saint-Kitts-et-Nevis", "kp": "Corée du Nord", "kr": "Corée du Sud",
    "kw": "Koweït", "kz": "Kazakhstan", "la": "Laos", "lb": "Liban", "lc": "Sainte-Lucie",
    "li": "Liechtenstein", "lk": "Sri Lanka", "lr": "Liberia", "ls": "Lesotho", "lt": "Lituanie",
    "lu": "Luxembourg", "lv": "Lettonie", "ly": "Libye", "ma": "Maroc", "mc": "Monaco", "md": "Moldavie",
    "me": "Monténégro", "mg": "Madagascar", "mh": "Îles Marshall", "mk": "Macédoine du Nord", "ml": "Mali",
    "mm": "Myanmar", "mn": "Mongolie", "mr": "Mauritanie", "mt": "Malte", "mu": "Maurice",
    "mv": "Maldives", "mw": "Malawi", "mx": "Mexique", "my": "Malaisie", "mz": "Mozambique",
    "na": "Namibie", "ne": "Niger", "ng": "Nigeria", "ni": "Nicaragua", "nl": "Pays-Bas",
    "no": "Norvège", "np": "Népal", "nz": "Nouvelle-Zélande", "om": "Oman", "pa": "Panama",
    "pe": "Pérou", "pg": "Papouasie-Nouvelle-Guinée", "ph": "Philippines", "pk": "Pakistan",
    "pl": "Pologne", "pr": "Porto Rico", "ps": "Palestine", "pt": "Portugal", "py": "Paraguay",
    "qa": "Qatar", "ro": "Roumanie", "rs": "Serbie", "ru": "Russie", "rw": "Rwanda",
    "sa": "Arabie saoudite", "sc": "Seychelles", "sd": "Soudan", "se": "Suède", "sg": "Singapour",
    "si": "Slovénie", "sk": "Slovaquie", "sl": "Sierra Leone", "sn": "Sénégal", "so": "Somalie",
    "sr": "Suriname", "st": "Sao Tomé-et-Principe", "sv": "Salvador", "sy": "Syrie", "sz": "Eswatini",
    "td": "Tchad", "tg": "Togo", "th": "Thaïlande", "tj": "Tadjikistan", "tl": "Timor oriental",
    "tm": "Turkménistan", "tn": "Tunisie", "to": "Tonga", "tr": "Turquie", "tt": "Trinité-et-Tobago",
    "tv": "Tuvalu", "tw": "Taïwan", "tz": "Tanzanie", "ua": "Ukraine", "ug": "Ouganda",
    "us": "États-Unis", "uy": "Uruguay", "uz": "Ouzbékistan", "va": "Vatican", "ve": "Venezuela",
    "vn": "Viêt Nam", "vu": "Vanuatu", "ws": "Samoa", "ye": "Yémen", "za": "Afrique du Sud",
    "zm": "Zambie", "zw": "Zimbabwe",
}

#: Pays mis en tête des listes (Afrique centrale / francophone).
PAYS_PRIORITAIRES = ["cg", "cd", "ga", "cm", "cf", "td", "ao", "fr", "be", "ci", "sn", "bj"]


def _ISO_PAR_NOM_FR():
    """{nom français normalisé: iso} (construit à la demande)."""
    global _CACHE_NOM_FR
    try:
        return _CACHE_NOM_FR
    except NameError:
        _CACHE_NOM_FR = {normaliser(n): i for i, n in NOMS_FR.items()}
        return _CACHE_NOM_FR


def iso_de(pays):
    """Code ISO-2 d'un pays écrit librement (« congo », « Congo-Brazzaville », « CG »), sinon ''."""
    info = _pays_pour_texte(pays) if pays else None
    return info[2] if info else ""


def nom_fr(pays):
    """Nom français canonique d'un pays saisi librement (ou le texte d'origine s'il est inconnu)."""
    iso = iso_de(pays)
    return NOMS_FR.get(iso, (pays or "").strip())


def choix_pays(valeur_actuelle=""):
    """Choix (valeur, libellé) pour un <select> : prioritaires, puis le reste trié."""
    tri = sorted(NOMS_FR.items(), key=lambda kv: normaliser(kv[1]))
    tete = [(NOMS_FR[i], NOMS_FR[i]) for i in PAYS_PRIORITAIRES if i in NOMS_FR]
    reste = [(nom, nom) for iso, nom in tri if iso not in PAYS_PRIORITAIRES]
    choix = [("", "— Choisir un pays —")] + tete + reste
    v = (valeur_actuelle or "").strip()
    if v and v not in dict(choix):
        connu = nom_fr(v)
        if connu not in dict(choix):
            choix.insert(1, (v, f"{v} (non reconnu sur la carte)"))
    return choix


def villes_par_pays():
    """{nom_fr_du_pays: [villes connues…]} pour les suggestions de ville."""
    sortie = {}
    for (cle_pays, ville) in VILLES:
        iso = PAYS_PAR_NOM.get(cle_pays, (None, None, None))[2]
        if not iso or iso not in NOMS_FR:
            continue
        nom = " ".join(m[:1].upper() + m[1:] for m in str(ville).split(" "))
        nom = "-".join(p[:1].upper() + p[1:] for p in nom.split("-"))
        liste = sortie.setdefault(NOMS_FR[iso], [])
        if nom not in liste:
            liste.append(nom)
    for liste in sortie.values():
        liste.sort(key=normaliser)
    return sortie
