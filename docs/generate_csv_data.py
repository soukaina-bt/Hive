#!/usr/bin/env python3
"""
Génère 5 fichiers CSV réalistes pour le dataset e-commerce.
Usage : python generate_csv_data.py
Output: customers.csv, products.csv, orders.csv, order_items.csv, reviews.csv
"""

import csv, random, os
from datetime import datetime, timedelta

random.seed(42)
OUT = os.path.dirname(os.path.abspath(__file__))

COUNTRIES = ["France","Maroc","Espagne","Allemagne","Belgique","Italie","Tunisie","Sénégal","Canada","USA"]
CITIES    = {"France":["Paris","Lyon","Marseille"],"Maroc":["Casablanca","Rabat","Marrakech"],
             "Espagne":["Madrid","Barcelone"],"Allemagne":["Berlin","Munich"],
             "Belgique":["Bruxelles","Liège"],"Italie":["Rome","Milan"],
             "Tunisie":["Tunis","Sfax"],"Sénégal":["Dakar","Saint-Louis"],
             "Canada":["Montréal","Toronto"],"USA":["New York","Los Angeles"]}
NAMES = ["Amina Benali","Youssef Khalid","Sara Martin","Lucas Dupont","Fatima Zahra","Ahmed Tazi",
         "Emma Blanc","Noah Petit","Lina Chraibi","Omar Benjelloun","Inès Roux","Mehdi Bensaid",
         "Clémence Morel","Karim Alaoui","Julie Laurent","Anas El Idrissi","Nadia Benkirane",
         "Pierre Lefebvre","Yasmine Bouazza","Hamza Tahiri"]
BRANDS    = ["TechZone","FashionHub","HomeStyle","SportPro","EcoShop"]
CATEGORIES = {
    "Électronique":  ["Smartphones","Laptops","Tablettes","Casques","Accessoires"],
    "Mode":          ["Vêtements Homme","Vêtements Femme","Chaussures","Sacs","Montres"],
    "Maison":        ["Décoration","Cuisine","Literie","Éclairage","Jardin"],
    "Sport":         ["Fitness","Football","Running","Natation","Yoga"],
    "Beauté":        ["Soin Visage","Maquillage","Parfums","Cheveux","Hygiène"],
}
PRODUCT_NAMES = {
    "Smartphones":["iPhone 15","Samsung S24","Pixel 8","Xiaomi 14","OnePlus 12"],
    "Laptops":["MacBook Air","Dell XPS","HP Spectre","Lenovo ThinkPad","Asus ZenBook"],
    "Tablettes":["iPad Pro","Samsung Tab","Surface Pro","Lenovo Tab","Amazon Fire"],
    "Casques":["Sony WH-1000XM5","AirPods Pro","Bose QC45","Jabra Elite","Sennheiser HD"],
    "Accessoires":["Chargeur USB-C","Coque iPhone","Câble HDMI","Souris sans fil","Clavier mécanique"],
    "Vêtements Homme":["Chemise Oxford","Jean Slim","Pull Cachemire","Veste Blazer","T-shirt Coton"],
    "Vêtements Femme":["Robe Florale","Blouse Soie","Jean Boyfriend","Manteau Laine","Top Modal"],
    "Chaussures":["Sneakers Nike","Mocassins Cuir","Bottines Femme","Sandales Été","Derby Homme"],
    "Sacs":["Sac à Dos","Tote Bag","Portefeuille","Sac Bandoulière","Valise Cabine"],
    "Montres":["Montre Classique","Smartwatch","Montre Plongée","Bracelet Acier","Montre Solaire"],
    "Décoration":["Vase Céramique","Tableau Abstrait","Plante Artificielle","Bougie Parfumée","Miroir Rond"],
    "Cuisine":["Cafetière","Blender","Air Fryer","Planche à Découper","Couteaux Chef"],
    "Literie":["Couette Duvet","Oreiller Mémoire","Drap Percale","Protège-Matelas","Couvre-Lit"],
    "Éclairage":["Lampe LED","Guirlande Lumineuse","Plafonnier","Lampe Bureau","Veilleuse"],
    "Jardin":["Arrosoir","Pelle Jardinage","Pot Terre Cuite","Graines Basilic","Tuyau Arrosage"],
    "Fitness":["Haltères 10kg","Tapis Yoga","Bande Élastique","Corde à Sauter","Kettlebell"],
    "Football":["Ballon Nike","Crampons","Protège-Tibias","Maillot PSG","Sac Sport"],
    "Running":["Chaussures Trail","Montre GPS","Gilet Réflecteur","Brassard Téléphone","Chaussettes Run"],
    "Natation":["Lunettes Natation","Bonnet Silicone","Combinaison Triathlon","Palmes","Pull-Buoy"],
    "Yoga":["Tapis Premium","Bloc Yoga","Sangle","Coussin Méditation","Sac Tapis"],
    "Soin Visage":["Crème Hydratante","Sérum Vitamine C","Masque Argile","Nettoyant Doux","Contour Yeux"],
    "Maquillage":["Foundation","Rouge à Lèvres","Mascara","Palette Ombres","Fond de Teint"],
    "Parfums":["Chanel N°5","Dior Sauvage","YSL Black Opium","Lancôme La Vie Est Belle","Armani Si"],
    "Cheveux":["Shampoing Kératine","Après-Shampooing","Masque Réparateur","Huile Argan","Spray Protecteur"],
    "Hygiène":["Dentifrice Blancheur","Déodorant 48h","Gel Douche","Lotion Corps","Rasoir Électrique"],
}
STATUSES = ["livré","en cours","annulé","remboursé","expédié"]
PAYMENTS  = ["carte_bancaire","virement","paypal","cash_on_delivery","apple_pay"]

def rand_date(start="2023-01-01", end="2024-12-31"):
    s = datetime.strptime(start,"%Y-%m-%d")
    e = datetime.strptime(end,"%Y-%m-%d")
    return (s + timedelta(days=random.randint(0,(e-s).days))).strftime("%Y-%m-%d")

# Customers
customers = []
for i in range(1, 501):
    name = random.choice(NAMES)
    country = random.choice(COUNTRIES)
    city = random.choice(CITIES[country])
    customers.append([i, name, f"user{i}@email.com", country, city,
                       rand_date("2022-01-01","2023-12-31"),
                       random.randint(18,65), random.choice(["M","F"])])
with open(f"{OUT}/customers.csv","w",newline="") as f:
    w=csv.writer(f); w.writerow(["customer_id","full_name","email","country","city","signup_date","age","gender"]); w.writerows(customers)

# Products
products, pid = [], 1
for cat, subs in CATEGORIES.items():
    for sub in subs:
        for pname in PRODUCT_NAMES[sub]:
            price = round(random.uniform(5, 1200), 2)
            products.append([pid, pname, cat, sub, random.choice(BRANDS), price, random.randint(0,500)])
            pid += 1
with open(f"{OUT}/products.csv","w",newline="") as f:
    w=csv.writer(f); w.writerow(["product_id","product_name","category","sub_category","brand","unit_price","stock_qty"]); w.writerows(products)

# Orders
orders = []
for oid in range(1, 2001):
    cid = random.randint(1,500)
    status = random.choices(STATUSES, weights=[60,15,10,5,10])[0]
    total  = round(random.uniform(10,2000),2)
    orders.append([oid, cid, rand_date(), status, random.choice(PAYMENTS), random.choice(COUNTRIES), total])
with open(f"{OUT}/orders.csv","w",newline="") as f:
    w=csv.writer(f); w.writerow(["order_id","customer_id","order_date","status","payment_method","shipping_country","total_amount"]); w.writerows(orders)

# Order items
items, iid = [], 1
for oid in range(1, 2001):
    for _ in range(random.randint(1,5)):
        prod = random.choice(products)
        qty  = random.randint(1,4)
        disc = round(random.choice([0,0,0,5,10,15,20])/100,2)
        sub  = round(prod[5]*qty*(1-disc),2)
        items.append([iid, oid, prod[0], qty, prod[5], disc*100, sub])
        iid += 1
with open(f"{OUT}/order_items.csv","w",newline="") as f:
    w=csv.writer(f); w.writerow(["item_id","order_id","product_id","quantity","unit_price","discount_pct","subtotal"]); w.writerows(items)

# Reviews
reviews, rid = [], 1
delivered = [o[0] for o in orders if o[3]=="livré"]
for oid in random.sample(delivered, min(800,len(delivered))):
    order = orders[oid-1]
    reviews.append([rid, oid, random.randint(1,len(products)), order[1],
                    random.randint(1,5), rand_date(), "Bon produit" if random.random()>0.3 else "Déçu"])
    rid += 1
with open(f"{OUT}/reviews.csv","w",newline="") as f:
    w=csv.writer(f); w.writerow(["review_id","order_id","product_id","customer_id","rating","review_date","comment"]); w.writerows(reviews)

print("✅ CSV générés :")
import os
for fn in ["customers.csv","products.csv","orders.csv","order_items.csv","reviews.csv"]:
    sz = os.path.getsize(f"{OUT}/{fn}")
    print(f"  {fn}  ({sz:,} bytes)")
