# -*- coding: utf-8 -*-
"""Phase 1 de la migration Notion -> Odoo : table de correspondance des etablissements FR.

Rapproche les etablissements Notion (BD Etablissements, Pays=France) avec les
partenaires Odoo via le champ `public_nas_name` (onglet "Formulaire commercial",
libelle "Nom NAS PUBLIC"), fourni par le module s6r_eurekam_crm.

Strategies en cascade :
    1. EXACT      : egalite stricte apres normalisation -> certain
    2. PREFIXE    : le nom Notion est un prefixe du NAS Odoo (Odoo descend au site,
                    ex. "06 - Nice - CHU" -> "06 - Nice - CHU - L'Archet 2")
    3. APPROCHE   : similarite difflib >= SEUIL -> a valider par un humain
    4. INTROUVABLE: aucun candidat

Sortie : migration/correspondance_etablissements.csv (a valider par Loic).
AUCUNE ecriture dans Odoo : ce script est en lecture seule / hors-ligne.
"""

import csv
import difflib
import os
import re
import unicodedata

SEUIL_DEPT = 0.62    # departement deja identique -> on peut etre plus permissif
SEUIL_GLOBAL = 0.80  # recherche dans tout Odoo -> seuil severe

# --- Etablissements Notion (BD Etablissements, Pays = France) : 161 ---
NOTION = [
    "01 - Bourg en Bresse - CH", "02 - Laon - CH", "02 - Saint Quentin - CH",
    "03 - Vichy - CH", "06 - Mougins - CL - Institut Arnaud Tzanck", "06 - Nice - CHU",
    "08 - Charleville-Mezieres -CH", "10 - Troyes - CH", "12 - Rodez - CH",
    "13 - Marseille - CLCC Paoli-Calmettes", "13 - Marseille - Hôpital Saint-Joseph - CL",
    "14 - Caen - CLCC François Baclesse", "14 - Caen - PCL du Parc", "16 - Angouleme - CH",
    "16 - Cognac - CHI Pays de Cognac", "16 - Soyaux - Centre Clinical - CL",
    "17 - La Rochelle - CH St Louis", "17 - Rochefort - CH", "17 - Saintes - CH Saintonge",
    "20 - Ajaccio - Notre Dame de la Miséricorde - CH", "20 - Corte - CH de Corte Tattone",
    "22 - Plérin - Hôpital Privé des Côtes d'Armor - HP",
    "23 - Sainte-Feyre - Centre Médical National MGEN", "24 - Périgueux - CH",
    "27 - Evreux - CHI Eure-Seine", "28 - Le Coudray - Chartres - CH",
    "29 - Quimper - CH de Cornouaille", "29 - Quimper - Clinique Mutualiste Bretagne HGO",
    "30 - Bagnols sur Cèze - CH", "30 - Nîmes - CHRU Caremeau", "30 - Nîmes - PCL Kenval",
    "31 - Toulouse - Oncopôle", "32 - Auch - CH", "33 - Bordeaux - Cli Tivoli-Ducos",
    "33 - Bordeaux - Polyclinique Bordeaux Nord Aquitaine", "33 - Libourne - CH",
    "34 - Castelnau-le-Lez - CL du Parc", "34 - Montpellier - CL Clémentville",
    "34 - Montpellier - CLCC Institut Régional du Cancer de Montpellier",
    "35 - CHP Saint Grégoire - CL", "35 - Rennes - CLCC Eugène Marquis",
    "35 - Saint-Malo - CH", "37 - Tours - Chamblay - Pole Santé Léonard de Vinci",
    "38 - Bourgoin-Jallieu - CH Pierre Oudot", "38 - Grenoble - CHU Grenoble Alpes",
    "40 - Dax - CH Cote d’Argent", "40 - Mont-de-Marsan - CH", "41 - Blois - CH",
    "42 - Roanne - CH", "42 - Saint-Etienne - CHU", "43 - Le Puy en Velay - CH Emile Roux",
    "44 - ICO (Angers)", "44 - ICO Saint Herblain", "44 - Nantes - CHU",
    "44 - Saint Nazaire - GCS PUI Cite Sanitaire", "45 - Orléans - CHU",
    "47 - Agen-Nerac - CH", "51 - Reims - CHU",
    "52 - Saint Dizier - CH Geneviève de Gaulle Anthonioz", "53 - Laval - CH",
    "53 - Laval - CH", "54 - Nancy - Hôpital Privé Nancy Lorraine",
    "54 - Nancy Metz - Université", "55 - Bar le duc - CH", "55 - Verdun - CH",
    "56 - Lorient - GH Bretagne Sud", "56 - Pontivy - CH du Centre-Bretagne",
    "56 - Vannes - CHBA", "56 - Vannes - Hôpital Privé Océane",
    "57 - Metz - CHRU Metz-Nancy-Thionville", "57 - Metz - Clinique Claude Bernard",
    "57 - Metz - HP Metz - Uneos", "59 - Douai - CH", "59 - Douai Dechy - CL Léonard de Vinci",
    "59 - GHICL - Lille - HP Saint Vincent de Paul", "59 - Roubaix - CH",
    "59 - Valenciennes - CH", "60 - Beauvais - CH",
    "60 - Compiègne - Polyclinique St Côme - CL", "60 - Creil - GH Public du Sud de l'Oise",
    "62 - Boulogne-sur-mer - CH", "62 - Lens - CH Dr Schaffner - CH",
    "63 - Clermont-Ferrand - CHU Gabriel Montpied", "63 - Clermont-Ferrand - CRLCC Jean PERRIN",
    "64 - Bayonne - CH Côte Basque", "64 - Bayonne - CL Belharra",
    "64 - Pau - CH François Mitterrand", "66 - Perpignan - CH",
    "66 - Perpignan - Clinique Saint Pierre", "67 - Strasbourg - Clinique de l’Orangerie",
    "67 - Strasbourg - GCS ICANS - Paul Strauss", "67 - Strasbourg - HUS site Hautepierre",
    "67 - Strasbourg - Saint Vincent Saint Anne - CL", "68 - Colmar - CH",
    "69 - Lyon - GHC - Hôpital Edouard Herriot", "69 - Lyon - GHE - Hôpital Mère-Enfant",
    "69 - Lyon - GHN - Hôpital de la Croix Rousse", "69 - Lyon - GHS - Hôpital Lyon SUD",
    "69 - Villefranche sur Saone - CH", "69 - Villeurbanne - Médipôle Lyon Villeurbanne - HP",
    "71 - Chalon sur Saone - CH", "72 - Le Mans - Centre de Cancerologie de la Sarthe (CCS)",
    "75 - APHP - Hôpital Armand Trousseau - CHU", "75 - APHP - Hôpital Saint-Antoine",
    "75 - Bbraun", "75 - Institut Curie - Site de Paris",
    "75 - Paris - Institut Medico-chirurgical Montsouris IMM",
    "75 - Paris 10 - APHP - Saint Louis", "75 - Paris 13 - APHP - Pitié Salpêtrière",
    "75 - Paris 15 - APHP - Necker", "75 - Paris 19 - APHP - Robert Debré",
    "76 - Dieppe - CH", "76 - Le Havre - CH Jacques Monod - GHH",
    "76 - Rouen - CHU Charles Nicolle", "76 - Rouen - CLCC Henri Becquerel",
    "76 - Rouen- CL - Clinique Mathilde",
    "76 - Saint-Aubin-lès-Elbeuf - CHI Elbeuf - Louviers",
    "77 - Férolles Attilly - Hop Forcilles - fondation Cognacq Jay",
    "77 - Marne la vallée - GHEF GH Est Parisien", "77 - Melun - GH Sud Île-de-France",
    "78 - Mantes la Jolie - CH François Quesnay", "78 - Poissy St Germain - CHI",
    "78 - Rambouillet - CH", "78 - Versailles Le Chesnay - CH Mignot",
    "79 - Bressuire - Nord Deux-Sèvres - CH", "79 - Niort - CH", "80 - Amiens - CHU",
    "81 - Albi - CH", "81 - Albi - CL Claude Bernard", "82 - Montauban - CH",
    "83 - Draguignan - CH", "83 - Frejus - CHI Frejus Saint Raphael",
    "83 - Toulon - CHI Toulon-La Seyne sur Mer", "83 - Toulon - HIA St Anne",
    "84 - Avignon - CH", "84 - Avignon - CL Institut Sainte Catherine", "84 - Cavaillon - CHI",
    "85 - La Roche sur Yon - CHD de Vendée",
    "86 - Site Chatellerault - CH Camille Guerin - CHU Poitiers",
    "86 - Site Poitiers - CHU Poitiers", "87 - Limoges - CHU", "87 - Limoges - CL Chenieux",
    "90 - Trevenans - Hôpital Nord Franche Comté", "91 - Longjumeau - CH - GHNE",
    "92 - Boulogne-Billancourt - APHP - Ambroise-Paré", "92 - Clamart - HIA Percy",
    "92 - Clichy - APHP - Beaujon", "92 - Institut Curie - Site de Saint-Cloud",
    "92 - Neuilly - CC Ambroise Paré - Hartmann", "93 - Bobigny - APHP - Avicenne",
    "93- Montfermeuil et Aulnay -  GHT GPNE", "94 - Creteil - APHP - Henri Mondor",
    "94 - Le Kremlin Bicetre - APHP - Hopital Bicêtre",
    "94 - Nogent-sur-Marne - Hôpital Privé Armand Brillard",
    "974 - La Reunion - CHU St-Pierre",
    "98 - Monaco - Nouveau Centre Hospitalier Princesse Grace",
    "Asept InMed", "Etablissement PREV France 2024 (Solde)", "Fresenius Kabi",
    "Owen Mumford", "Zentiva",
]

# --- Partenaires Odoo FR avec public_nas_name renseigne : (id, nas) ---
ODOO = [
    (1779, "01 - Bourg en Bresse - CH"), (17654, "01-Bourg en Bresse-Clinique Convert - CL"),
    (17480, "01-Oyonnax-Haut-Bugey-CH"), (1593, "02 - Saint Quentin - CH"),
    (17592, "02 - Soissons - CH"), (17655, "02-Laon-CH"),
    (17430, "03-Moulins-Polyclinique Saint Odilon-CL"), (17593, "03-Vichy-Jacques Lacarin-CH"),
    (17494, "04-Manosque-Louis Raffalli-CH"), (17431, "05-Briançon-CH des Escartons"),
    (2667, "06 - Mougins - CL - Institut du Cancer de Mougins (Arnaud Tzanck)"),
    (952, "06 - Nice - CHU - L'Archet 2"), (17434, "06- Cagnes/mer- Polyclinique Saint Jean-CL"),
    (17595, "06-Antibes-Juan-les-Pins-CH"), (17495, "06-Cannes-CH"), (17496, "06-Grasse-CH"),
    (17657, "06-Nice-Cliniques du parc impérial-CL"), (17436, "07-Annonay-CH"),
    (17497, "07-Aubenas-Ardèche Méridionale-CH"), (17435, "07-Privas-Vals d'Ardèche-CH"),
    (1223, "08 - Charleville-Mezieres -CH"),
    (17498, "09-Saint Jean de Verges-Vallées de l'Ariège-CHI"), (1594, "10 - Troyes - CH"),
    (17437, "10 - Troyes - Hôpitaux Champagne Sud- SIMONE VEIL - CH"),
    (17499, "11-Carcassonne-CH"), (17500, "11-Narbonne-Hopital Privé du Grand Narbonne -CL"),
    (17439, "12-Millau-CH"), (17596, "12-Rodez -Jacques Puel-Bourran -CH"),
    (17501, "12-Villefranche de Rouergue-CH"), (583, "13 - Marseille - CLCC Paoli-Calmettes"),
    (17573, "13 - Marseille - Hôpital Saint-Joseph - CL"),
    (17659, "13-Aix en Provence-Hôpital Privé de Provence-HP"), (17441, "13-Aubagne-CH"),
    (17505, "13-Aubagne-Hôpital Privé la Casamance-HP"), (17660, "13-Hôpial du pays Salonais-CH"),
    (17502, "13-Marseille La Timone-CHU"), (17506, "13-Marseille-Hôpital Européen-HP"),
    (17504, "13-Marseille-Hôpital privé Beauregard-HP"),
    (17503, "13-Marseille-hôpital Privé Clairval-HP"), (677, "14 - Caen - PCL du Parc"),
    (2682, "14-Caen-Centre François Baclesse-CLCC"), (17443, "14-Lisieux-CH"), (17618, "14-Vire-CH"),
    (17507, "15-Aurillac-CMC les Tronquières-CL"), (17760, "15-Aurillac-Henri Mondor-CH"),
    (1854, "16 - Angouleme - CH"), (17661, "16 - Pays de Cognac - CHI"),
    (2916, "16 - Soyaux - Centre Clinical ELSAN"), (479, "17 - La Rochelle - CH St Louis"),
    (2761, "17 - Rochefort - CH"), (1592, "17 - Saintes - CH Saintonge"),
    (17508, "17-Vaux-sur-mer- Royan - CH"), (17662, "18-Bourges-Jacques Cœur-CH"),
    (17663, "18-Vierzon-CH"), (17639, "19 - Brive-la-Gaillarde - CH"),
    (2641, "20 - Ajaccio - CH Notre Dame de la Miséricorde"),
    (1321, "20 - Ajaccio - CH de Castelluccio"), (1812, "20 - Corte - CH de Corte Tattone"),
    (17646, "20-Bastia-CH"), (17696, "20-Bastia-Clinique Maymard-CL"), (17509, "21-Dijon-CHU"),
    (17665, "21-Dijon-Clinique Fondation Clément Drevon-CL"),
    (17664, "21-Talant-Clinique mutualiste Benigne Joly-CL"), (17510, "22- Dinan - René Pleven - CH"),
    (17597, "22-Lannion- Pierre le Damany - CH"), (17482, "22-Lannion-Polyclinique du Trégor-CL"),
    (17651, "22-Plérin-Hôpital Privé des Côtes d'Armor-HP"), (17666, "23 - Guéret - CH"),
    (17511, "23 - Sainte-Feyre - Centre Médical National MGEN - CL"), (17532, "24-Nontron-CH"),
    (17537, "24-Périgueux-CH"), (17667, "24-Périgueux-Polyclinique Francheville-CL"),
    (17491, "25 - Besançon - Hôpital Jean Minjoz - CHU"), (323, "26 - Valence - CH"),
    (17668, "26-Clinique générale de Valence-CL"), (17669, "26-Montélimar-CH"),
    (17512, "26-Romans sur Isère-Hôpitaux Drôme Nord-CH"), (358, "27 - Evreux - CHI Eure-Seine"),
    (17670, "27-Evreux-Clinique Chirurgical Pasteur-CL"), (2672, "28 - Chartres - CH"),
    (17446, "28-Châteaudun-CH"), (17672, "28-Dreux-CH Victor Jousselin"),
    (17575, "28-Nogent le Rotrou-CH"), (261, "29 - Quimper - CH de Cornouaille"),
    (44760, "29 - Quimper - Clinique Mutualiste de Bretagne Occidentale"),
    (17586, "29-Brest-Clinique Pasteur-Lanroze-CL"), (17447, "29-Douarnenez-Michel Mazéas-HP"),
    (17585, "29-Morlaix-Pays de Morlaix-CH"),
    (17640, "29-Quimper-Clinique Saint Michel  & Sainte-Anne-CL"),
    (1660, "30 - Bagnols sur Cèze - CH"), (202, "30 - Nîmes - CHRU Caremeau"),
    (1970, "30 - Nîmes - PCL Kenval"), (17673, "30-CH Alès-Cévennes"), (520, "31 - Toulouse - Oncopôle"),
    (17675, "31 -Saint-Jean- Clinique de L'Union-CL"),
    (17764, "31- Quint Fonsegrives - Clinique La Croix du Sud - CL"),
    (17674, "31-Cornebarrieu-Clinique des Cèdres-CL"), (17598, "31-Muret-Clinique d'Occitanie-CL"),
    (17448, "31-Saint-Gaudens-CH Comminges-Pyrénées"), (17531, "31-Toulouse-Clinique pasteur-CL"),
    (1058, "32 - Auch - CH"), (1960, "33 - Bordeaux - Cli Tivoli-Ducos"),
    (17641, "33 - Bordeaux - Haut-Lévêque - CHU"), (17682, "33 - Bruges - Polyclinique Jean Villar - CL"),
    (17678, "33 - Clinique d'Arcachon - GBNA - CL"), (17533, "33 - Libourne - Robert Boulin - CH"),
    (17681, "33 - Polyclinique Bordeaux Rive Droite - GBNA - CL"), (17676, "33- Bordeaux Pellegrin - CHU"),
    (17680, "33-Hôpital suburbain du bouscat-CH"), (17765, "33-Langon-Sainte Anne-CL"),
    (17679, "33-Langon-Sud Gironde-CH"), (17642, "34 - Castelnau-le-Lez - Clinique du Parc"),
    (17644, "34 - Montpellier - Clinique Clémentville - CL"),
    (17424, "34- Boujan sur Libron- Polyclinique Saint Privat- CL"),
    (17449, "34-Béziers-Clinique Champeau Méditerranée-CL"),
    (17645, "34-Montpellier-Clinique Languedoc Mutualité Beau Soleil-CL"),
    (199, "34-Montpellier-Hôpital Arnaud de Villeneuve-CHU"), (17643, "34-Sète-bassin de Thau-CHI"),
    (17620, "35 - Cesson-Sévigné - Hôpital Privé Sévigné - HP"), (107, "35 - Rennes - CLCC Eugène Marquis"),
    (17683, "35-CHP Saint Grégoire-CL"), (17450, "35-Fougères-CH"), (17513, "35-Rennes-CHU Sud"),
    (17619, "35-Rennes-Polyclinique Saint Laurent-CL"),
    (17599, "35-Saint-Malo-Clinique Côte d'Emeraude-CL"), (17684, "36-Châteauroux-CH"),
    (17685, "37 - Saint-Benoît-la-Forêt - Hôpital du Chinonais - CH"),
    (1268, "37 - Tours - Chamblay - Pole Santé Léonard de Vinci"),
    (17514, "37-Saint Cyr sur Loire- NCT+ -CL"), (157, "38 - Bourgoin-Jallieu - CH"),
    (17452, "38-Vienne-Lucien Hussel-CH"), (17576, "38-Voiron-Pierre Bazin-CH"),
    (17483, "39 -CH Louis Pasteur - Dole"), (17686, "39-Lons le Saunier-CH"),
    (271, "40 - Dax - CH Cote dArgent"), (1654, "40 - Mont-de-Marsan - CH"), (244, "41 - Blois - CH"),
    (17515, "41- Vendôme-CH"), (17687, "41-La Chaussée Saint Victor - Polyclinique de Blois - CL"),
    (17689, "42-Roanne-CH"), (17634, "42-Saint Etienne-CHU"),
    (17621, "42-Saint Etienne-Hôpital privé de la Loire-HP"), (139, "43 - Le Puy en Velay - CH Emile Roux"),
    (17453, "44 - Chateaubriant - Noze - Pouance - CH"), (1596, "44 - Saint Nazaire - GCS PUI Cite Sanitaire"),
    (2824, "44 - Saint-Herblain - ICO"), (165, "45 - Orléans - CHU"), (17635, "45 - Pithiviers - CH"),
    (17601, "45 - Saran - Clinique Oreliance -CL"),
    (17600, "45-Amilly-CH de l'agglomération Montargeoise - CH"), (17690, "45-Gien-Clinique Jeanne d'Arc-CL"),
    (17454, "46-Figeac-Clinique font redonde-CL"), (17697, "47 - Agen - Clinique Esquirol Saint-Hilaire - CL"),
    (1091, "47 - Agen - Nerac - CH"), (17692, "47-Marmande-Tonneins-CHI"),
    (17693, "47-Villeneuve-sur-Lot-Pôle de santé du villeneuvois-CL"), (17455, "48-Mende-CH Lozère"),
    (590, "49 - Angers - ICO"), (17698, "49 - Saumur - CH"),
    (17702, "50 - Saint-Martin-des-Champs- Polyclinique de la Baie - Avranches - CL"),
    (17699, "50 -Saint-Lô- Mémorial France Etats-Unis- CH"), (17701, "50-CH d'Avranches-Granville"),
    (1776, "51 - Reims - CHU"), (17456, "51-Chalons en Champagne-CH"),
    (17484, "51-Epernay-Auban Moët Epernay-CH"), (17516, "51-Reims-Clinique COURLANCY-CL"),
    (2158, "52 - Saint Dizier - CH Geneviève de Gaulle Anthonioz"), (1608, "52-Saint-Dizier-CH"),
    (17577, "53-Laval-CH"), (17703, "53-Laval-Polyclinique du Maine-CL"), (17617, "54 - Lunéville-CH"),
    (2101, "54 - Nancy - Polyclinique de Gentilly"), (1201, "54 - Nancy - Polyclinique de Gentilly - CL"),
    (1617, "55 - Bar le duc - CH"), (1614, "55 - Verdun - CH"), (1284, "56 - Lorient - GH Bretagne Sud"),
    (1678, "56 - Pontivy - CH du Centre-Bretagne"), (1126, "56 - Vannes - CHBA"),
    (17584, "56-Lorient-Clinique Mutualiste de la Porte de l'Orient-CL"),
    (17578, "56-Ploërmel-Alphonse Guérin-CH"), (17704, "56-Vannes-Hôpital privé océane-HP"),
    (6383, "57 - Metz - Clinique Claude Bernard"), (1597, "57 - Metz - UNEOS hôpital Robert Schuman - CL"),
    (31377, "57-Metz-Thionville(Ars-Laquenexy)- CHR"), (17602, "57-Metz-Thionville(Ars-Laquenexy)- CHR"),
    (17457, "57-Sarrebourg-Saint Nicolas de Sarrebourg-CH"), (17587, "58-Nevers-CH"),
    (17705, "58-Nevers-Polyclinique du val de loire-CL"), (368, "59 - Douai Dechy - CL Léonard de Vinci"),
    (1795, "59 - GHICL - Lille - HP Saint Vincent de Paul"), (308, "59 - Roubaix - CH"),
    (17622, "59-Armentières-CH"), (17603, "59-Douai-CH"), (17460, "59-Dunkerque-CH"),
    (17713, "59-Hazebrouk-CH"), (17707, "59-Lille-CHU"), (17458, "59-Lille-Centre Oscar Lambret-CLCC"),
    (17708, "59-Lille-Hôpital Privé le bois-HP"), (17613, "59-Sainte Marie Cambrai-CL"),
    (17461, "59-Tourcoing-CH"), (17768, "59-Valencienne-Les Dentellières-CLCC"),
    (17647, "59-Valenciennes-CH"), (17604, "60-Beauvais-CH"), (17709, "60-Compiègne-CH"),
    (17710, "60-Compiègne-Polyclinique St Côme-CL"),
    (1769, "60-Creil-Groupement Hospitalier Public du Sud de l’Oise-GH"),
    (17711, "60-Gouvieux-Hôpital privé de Chantilly-CL"), (17712, "61-CHI d'Alençon et Mamers"),
    (17462, "61-Flers-CH"), (2840, "62 - Boulogne sur Mer - CH"), (17606, "62-Beuvry-CH de Bethune"),
    (17605, "62-Beuvry-Clinique Ambroise Paré-CL"), (17716, "62-Béthune-Clinique Anne d'Artois-CL"),
    (17715, "62-Calais-CH"), (17633, "62-Coquelles-Clinique des 2 Caps-CL"),
    (17714, "62-Helfaut-CH Région de Saint Omer"), (17648, "62-Lens-CH  Dr Schaffner"),
    (17608, "62-Rang du Filiers-CH Arrondissement de Montreuil sur mer"),
    (177, "63 - Clermont-Ferrand - CHU Gabriel Montpied"), (1294, "63 - Clermont-Ferrand - CRLCC Jean PERRIN"),
    (17717, "63-Clermont Ferrand-Pôle Santé République-CL"), (2936, "64 - Bayonne - CL Belharra"),
    (336, "64 - Bayonne - Côte Basque - CH"), (287, "64 - Pau - CH François Mitterrand"),
    (17718, "64-Biarritz-Clinique Aguiléra-CL"), (17719, "64-Pau-Clinique Marzet-CL"),
    (17720, "64-Saint Jean de Luz-Polyclinique Côte basque Sud-CL"),
    (17463, "65 - Tarbes - Centre Hospitalier de Bigorre Tabres-Lourdes"),
    (17609, "65 - Tarbes - polyclinique de l'Ormeau - CL"), (17721, "65-Bigorre-CHI"),
    (2602, "66 - Perpignan - CL St Pierre"), (2864, "67 - Strasbourg - CL GH Saint Vincent Saint Anne"),
    (348, "67 - Strasbourg - CLCC Centre Paul Strauss"), (17653, "67 - Strasbourg - Clinique Rhéna"),
    (2006, "67 - Strasbourg - HUS site Hautepierre"), (17518, "67- Haguenau - CH"),
    (17637, "67-Saverne-CH"), (17485, "67-Sélestat-CH"), (1848, "68-Hôpitaux Civils de Colmar-CH"),
    (17519, "68-Mulhouse-Emile Muller-CH"), (17624, "68-Saint Louis-Clinique des 3 frontières-CL"),
    (1845, "69 - Lyon - GHS - Hôpital Lyon SUD"), (2598, "69 - Lyon - GHT Rhône Centre - HCL - CHU"),
    (1682, "69 - Lyon - GHT Rhône Centre - HCL - CHU"), (17770, "69 - Lyon - GHT Rhône Centre GHE - HCL - CHU"),
    (1415, "69 - Villefranche sur Saone - CH"), (17625, "69-Arnas-Clinique du Beaujolais-CL"),
    (17723, "69-Lyon-Clinique de la sauvegarde-CL"), (17579, "69-Lyon-Clinique protestante de Lyon-CL"),
    (17763, "69-Lyon-Hôpital privé Jean Mermoz-HP"), (17464, "69-Lyon-St Joseph St Luc-CL"),
    (17757, "69-Médipôle Lyon-Villeurbanne-HP"), (17465, "69-Rilleux la Pape-Polyclinique Lyon-Nord - CL"),
    (17466, "69-Saint Priest-Hôpital privé de l'Est Lyonnais-HP"), (17773, "69-Sainte Colombe-Clinique Trénel-CL"),
    (17722, "69-Sainte Foy lès Lyon-Clinique Charcot-CL"),
    (17493, "70-Vesoul-Groupement Hospitalier Haute Saône-CH"), (1521, "71 - Chalon sur Saone - CH"),
    (17724, "71-Chanaux de Mâcon-CH"), (17726, "71-Charnay-lès-Mâcon-Polyclinique du Val de Saône-CL"),
    (1961, "72 - Le Mans - CCS - Centre Cancero Sarthe"),
    (17626, "72-Le Grand-Lucé-Fondation Centre Médical Georges Coulon-CL"), (17729, "73 - Aix-les-bains - CH"),
    (17776, "73 -Challes les Eaux- Hôpital privé Médipôle de Savoie-HP"), (17728, "73-Albertville Moutiers-CH"),
    (17467, "73-Saint Jean de Maurienne-CH"), (17732, "74-Annemasse-Hôpital privé Pays de Savoie-HP"),
    (17468, "74-Passy-Centre Médical specialisé Praz coutant-CL"),
    (17731, "74-Saint Julien en Genevois-CHI Sud Leman Valserine"),
    (17758, "75 - AP HP - Direction - AGEPS Central achats"),
    (17426, "75 - AP-HP - Hôpital Armand Trousseau - La Roche Guyon - CHU"),
    (1863, "75 - Institut Curie - Site de Paris"), (64, "75 - Paris - APHP Saint Antoine"),
    (17735, "75 - Paris - Clinique Saint-Jean-de-Dieu - CL"), (1354, "75 - Paris 10 - APHP - Saint Louis"),
    (48, "75 - Paris 13 - APHP - Pitié Salpêtrière"), (496, "75 - Paris 14 - GH Paris Saint Joseph"),
    (579, "75 - Paris 14 - Institut Mutualiste Montsouris - HP"), (1691, "75 - Paris 15 - APHP - Necker"),
    (962, "75 - Paris 19 - APHP - Robert Debré"), (17736, "75 - Paris-Clinique Bizet-CL"),
    (17427, "75- AP-HP - Hôpital Européen Georges Pompidou - CHU"),
    (17734, "75-Paris-GH Diaconesses Croix Saint-Simon-CL"), (17759, "75-Paris-GIP Resah-Idf - CENTRALE"),
    (2795, "76 - Dieppe - CH"), (17772, "76 - Fécamp - CHI du Pays des Hautes Falaises"),
    (506, "76 - Le Havre - CH Jacques Monod"), (1686, "76 - Rouen - CHU Charles Nicolle"),
    (118, "76 - Rouen - CLCC Henri Becquerel"), (17628, "76 - Rouen - Clinique de l'Europe - CL"),
    (2090, "76 - Saint-Aubin-lès-Elbeuf - CHI Elbeuf - Louviers"), (17610, "76-Le Havre-Clinique des Ormeaux-CL"),
    (17522, "76-Rouen-Clinique Mathilde-CL"), (17611, "76-Rouen-Clinique Saint-Hilaire-CL"),
    (17523, "77 - CH Sud 77 - Site Fontainebleau"), (17524, "77 - CH Sud 77 - Site Montereau et Nemours"),
    (1483, "77 - Férolles Attilly - Hop Forcilles - fondation Cognacq Jay"),
    (498, "77 - Melun - GH Sud Île-de-France"),
    (17486, "77 -Mareuil-lès-Meaux- Clinique Saint Faron (Groupe St Gatien)-CL"),
    (1171, "77-Meaux-CH -GHEF site de Meaux"), (17629, "77-Melun-Clinique Saint-Jean-L'Ermitage-CL"),
    (17469, "77-Provins-Léon Binet-CH"), (142, "78 - Mantes la Jolie - CH François Quesnay"),
    (17767, "78 - Meulan - Meulan les Mureaux - CHI"), (773, "78 - Poissy St Germain - CHI"),
    (307, "78 - Rambouillet - CH"), (325, "78 - Versailles Le Chesnay - CH Mignot"),
    (17738, "78 - Versailles-Hôpital La Porte Verte-CL"),
    (17739, "78-Le Port-Marly-Centre Hospitalier Privé de l'Europe-CL"),
    (2808, "79 - Bressuire - Nord Deux-Sèvres - CH"), (1545, "79 - Niort - CH"), (1481, "80 - Amiens - CHU"),
    (17774, "80 - Amiens - Clinique de l'Europe"), (17525, "80-CH d'Abbeville"), (2058, "81 - Albi - CH"),
    (1639, "81 - Albi - CL Claude Bernard"), (17742, "81- Castres-Mazamet -CH"), (17526, "82-Montauban-CH"),
    (17612, "82-Montauban-Clinique Pont de Chaume-CL"), (1600, "83 - Frejus - CHI Frejus Saint Raphael"),
    (1583, "83 - Toulon - CHI Toulon-La Seyne sur Mer"), (17743, "83-Draguignan-CH"),
    (17470, "83-La Seyne sur Mer-Clinique Cap d'or-CL"),
    (17745, "83-Toulon-Hôpital Privé Toulon Hyères Siège GIE Var-HP"),
    (1785, "84 - Avignon - CL Institut Sainte Catherine"), (17649, "84-Avignon-CH"),
    (17746, "84-Lauris-Cavaillon-Lauris-CHI"), (130, "85 - La Roche sur Yon - CHD de Vendée"),
    (17527, "85-des Sables d'Olonne - CH"), (17762, "86 - Polyclinique de Poitiers -CL"),
    (9811, "86 - Site Chatellerault - CH Camille Guerin - CHU Poitiers"),
    (1611, "86 - Site Poitiers - CHU Poitiers"), (2651, "87 - Limoges - CHU"), (1061, "87 - Limoges - CL Chenieux"),
    (17472, "88 -Saint Dié des Vosges- CH Saint Dié"), (17487, "88-Epinal-Clinique la ligne bleue - Sogecler-CL"),
    (17473, "88-Epinal-Emile Durkheim-CH"), (17471, "88-Neufchâteau-CH"), (17474, "88-Remiremont-CH"),
    (17747, "89-Auxerre-CH"), (17748, "89-Auxerre-Polyclinique Sainte Marguerite - Groupe C2S-CL"),
    (17589, "89-SENS-CH"), (17481, "89-Sens-Clinique Paul Picquet-CL"),
    (17492, "90-Trévenans- CH- Hôpital Nord Franche-Comté - Site du Mittan"), (2053, "91 - Longjumeau - GHNE"),
    (17476, "91 -Corbeil-Essonnes- Sud Francilien-CH"), (17528, "91-Arpajon-CHG"),
    (17475, "91-Briis-sous-Forges- CH de Bligny - CH"), (17614, "91-Ris Orangis-Clinique Pasteur-CL"),
    (17488, "91-Yerres-Hôpital Privé du Val d'Yerres-CL"),
    (1335, "92 - Boulogne-Billancourt - APHP - Ambroise-Paré"), (1332, "92 - Clichy - APHP - Beaujon"),
    (17638, "92 - Clinique de Meudon (=Cl du Plateau )-CL"), (573, "92 - Institut Curie - Site de Saint-Cloud"),
    (17489, "92 - Levallois-Perret-Hôpital Franco-Britannique-CL"),
    (44873, "92 - Neuilly - CC Ambroise Paré - Hartmann"), (17632, "92 - Neuilly - CH Rives de Seine"),
    (17583, "92 - Neuilly - Hopital Americain - CL"), (17529, "92 - Suresnes - Hôpital Foch - CL"),
    (461, "92 - Villeneuve-La-Garenne - Fondation Santé Service HAD"),
    (17477, "92 -Boulogne-Billancourt- Clinique de la porte de St Cloud-CL"),
    (17428, "92 -Clamart- APHP- Hôpital Antoine-Béclère-CHU"), (17652, "92- Antony - Hopital Privé d'Antony - HP"),
    (17749, "92-Clamart- Percy - HIA - CH"), (1790, "93 - Bobigny - APHP - Avicenne"),
    (17650, "93 - Montfermeil - CHI"), (17581, "94 - APHP-Hôpital Emile Roux-CHU"),
    (1967, "94 - Creteil - APHP - Henri Mondor"), (1782, "94 - Le Kremlin Bicetre - APHP - Hopital Bicêtre"),
    (17479, "94 -Bry sur Marne- Sainte Camille-CH"), (17750, "94 -Nogent-sur-Marne- Hôpital Privé Armand Brillard-CL"),
    (17478, "94-Créteil-CHI"), (17490, "94-Hôpital Privé de Thiais-CL"), (17530, "94-Villejuif-Gustave Roussy-CLCC"),
    (17630, "94-Villeneuve St Georges-CHI"), (17752, "95 - Osny - Hôpital privé Sainte Marie - HP"),
    (17755, "95 - Pontoise - GHT NOVO - CH René Dubos"), (17756, "95-Argenteuil-CH"), (17754, "95-Gonesse-CH"),
    (17751, "95-Sarcelles-Hôpital privé Nord Parisien-CL"), (17753, "95-Sarcelles-Institut de Cancérologie Paris Nord-CL"),
    (31355, "97 - Martinique - CHU"), (17695, "97-Clinique Sainte Clotilde-CL"),
    (17694, "971 - Guadeloupe - Pointe à Pitre/Abymes - CHU"), (17775, "973 - Guyane - Cayenne - André Rosemon - CH"),
    (1029, "974 - La Réunion - St Pierre - Site Sud - CHU"), (45200, "98 - Nouvelle Calédonie - CIPAC"),
    (45201, "98 - Nouvelle Calédonie - CIPAC"), (17771, "98 - Polynesie Francaise - CHPF"),
    (22294, "98 - Princesse Grace - CH"), (31384, "ARS Corse"), (31368, "ARS grand-Est"),
    (31375, "CH Claudel"), (31369, "Groupe LPVIA"), (31362, "Groupe Vivalto"),
]

# Lignes Notion qui ne sont pas des etablissements de soin -> a exclure du perimetre
NON_ETABLISSEMENTS = {
    "Asept InMed", "Fresenius Kabi", "Owen Mumford", "Zentiva", "75 - Bbraun",
    "Etablissement PREV France 2024 (Solde)",
}


def norm(s):
    """Normalise : sans accents, minuscules, ponctuation -> espaces, espaces compactes."""
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def dept(s):
    """Numero de departement en tete ('06 - Nice - CHU' -> '6', '974 - ...' -> '974')."""
    m = re.match(r"\s*(\d{1,3})\b", s or "")
    return str(int(m.group(1))) if m else None


def match_one(nom, odoo_norm):
    """Cascade contrainte par departement : EXACT -> PREFIXE -> APPROCHE.

    Le numero de departement est une CONTRAINTE DURE : on ne compare qu'aux
    partenaires du meme departement. Sans cela, difflib propose des absurdites
    ("03 - Vichy - CH" -> "32 - Auch - CH"). Si le departement n'isole aucun
    candidat, on retombe sur une recherche globale avec un seuil plus severe.
    """
    n = norm(nom)
    d = dept(nom)

    pool = [o for o in odoo_norm if d and o["dept"] == d]
    contraint = bool(pool)
    if not pool:
        pool = odoo_norm

    exacts = [o for o in pool if o["norm"] == n]
    if exacts:
        return ("EXACT", 1.0, exacts)

    # prefixe sur frontiere de mot : "06 nice chu" -> "06 nice chu l archet 2"
    prefixes = [o for o in pool if o["norm"].startswith(n + " ")]
    if prefixes:
        return ("PREFIXE", 0.95, prefixes)

    # l'inverse : Notion plus long que Odoo
    inverses = [o for o in pool if n.startswith(o["norm"] + " ")]
    if inverses:
        return ("PREFIXE_INV", 0.90, inverses)

    # INCLUSION : tous les mots Notion figurent dans le NAS Odoo, meme dans le
    # desordre et noyes parmi d'autres. C'est le signal le plus fiable ici :
    # "03 vichy ch" est inclus dans "03 vichy jacques lacarin ch" alors que
    # difflib ne donne que 0.58. On retient le candidat qui ajoute le moins de
    # mots parasites.
    n_tokens = set(n.split())
    if n_tokens:
        inclus = [o for o in pool if n_tokens <= set(o["norm"].split())]
        if inclus:
            def extra(o):
                return len(set(o["norm"].split()) - n_tokens)
            inclus.sort(key=extra)
            best = extra(inclus[0])
            tied = [o for o in inclus if extra(o) == best]
            score = round(len(n_tokens) / float(len(n_tokens) + best), 3)
            return ("INCLUSION", score, tied)

    seuil = SEUIL_DEPT if contraint else SEUIL_GLOBAL
    scored = sorted(
        ((difflib.SequenceMatcher(None, n, o["norm"]).ratio(), o) for o in pool),
        key=lambda t: t[0], reverse=True,
    )
    if scored and scored[0][0] >= seuil:
        best = scored[0][0]
        strat = "APPROCHE_DEPT" if contraint else "APPROCHE_GLOBAL"
        return (strat, round(best, 3), [o for r, o in scored if r == best])
    return ("INTROUVABLE", round(scored[0][0], 3) if scored else 0.0,
            [scored[0][1]] if scored else [])


def main():
    odoo_norm = [{"id": i, "nas": nas, "norm": norm(nas), "dept": dept(nas)}
                 for i, nas in ODOO]
    out_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(out_dir, "correspondance_etablissements.csv")

    stats = {}
    vus = set()
    rows = []
    for nom in NOTION:
        if nom in NON_ETABLISSEMENTS:
            statut, strat, score, cands = "HORS PERIMETRE", "-", "", []
        else:
            strat, score, cands = match_one(nom, odoo_norm)
            if strat in ("EXACT", "PREFIXE", "PREFIXE_INV", "INCLUSION") and len(cands) == 1:
                statut = "CERTAIN"
            elif strat == "INTROUVABLE":
                statut = "INTROUVABLE"
            elif len(cands) > 1:
                statut = "AMBIGU"
            else:
                statut = "A VALIDER"
        if nom in vus:
            statut = "DOUBLON NOTION"
        vus.add(nom)

        stats[statut] = stats.get(statut, 0) + 1
        rows.append({
            "notion_nom": nom,
            "statut": statut,
            "strategie": strat,
            "score": score,
            "odoo_id": cands[0]["id"] if cands else "",
            "odoo_nas": cands[0]["nas"] if cands else "",
            "autres_candidats": " | ".join(f'{c["id"]}:{c["nas"]}' for c in cands[1:4]),
        })

    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), delimiter=";")
        w.writeheader()
        w.writerows(rows)

    total = len(rows)
    print(f"Notion FR : {total} lignes | Odoo FR avec NAS : {len(ODOO)}")
    print("-" * 58)
    for s in ("CERTAIN", "A VALIDER", "AMBIGU", "INTROUVABLE", "DOUBLON NOTION", "HORS PERIMETRE"):
        n = stats.get(s, 0)
        if n:
            print(f"  {s:<16} {n:>4}  ({n * 100.0 / total:.1f}%)")
    auto = stats.get("CERTAIN", 0)
    print("-" * 58)
    print(f"Rapproches automatiquement : {auto}/{total} ({auto * 100.0 / total:.1f}%)")
    print(f"CSV -> {csv_path}")

    print("\n--- A ARBITRER (hors CERTAIN / HORS PERIMETRE) ---")
    for r in rows:
        if r["statut"] not in ("CERTAIN", "HORS PERIMETRE"):
            print(f'[{r["statut"]:<14}] {r["notion_nom"]}')
            if r["odoo_nas"]:
                print(f'{"":<17} -> {r["score"]} | {r["odoo_id"]} : {r["odoo_nas"]}')


if __name__ == "__main__":
    main()
