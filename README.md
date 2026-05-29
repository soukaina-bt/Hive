# Guide de Démarrage — Ecommerce Dashboard

---

##  Ordre de démarrage (utilisations suivantes)

```
1. Démarrer la VM VMware
2. Lancer les services Hadoop/Hive  →  Étape 1
3. Lancer le backend FastAPI         →  Étape 3  (PowerShell 1)
4. Lancer le frontend React          →  Étape 4  (PowerShell 2)
```

> **Note :** L'étape 2 (CSV + tables Hive) n'est à faire qu'**une seule fois**.
> Les données restent dans HDFS entre les redémarrages.

---

##  Étape 1 — Démarrer les services sur la VM Cloudera

Connecte-toi à la VM puis lance les services dans cet ordre :

```bash
# 1. Libérer les ports bloqués
sudo fuser -k 50070/tcp
sudo fuser -k 8020/tcp

# 2. HDFS
sudo service hadoop-hdfs-namenode start
sudo service hadoop-hdfs-datanode start

# 3. YARN
sudo service hadoop-yarn-resourcemanager start
sudo service hadoop-yarn-nodemanager start

# 4. Sortir du Safe Mode
sudo -u hdfs hdfs dfsadmin -safemode leave

# 5. Hive
sudo service hive-metastore start
sleep 20
sudo service hive-server2 start
```

### Vérification

```bash
jps
sudo netstat -tlnp | grep 10000   # doit afficher le port 10000
```

---

##  Étape 2 — Préparer les données Hive *(1ère fois seulement)*

### Sur Windows — Copier les CSV vers la VM

```powershell
scp -oHostKeyAlgorithms=+ssh-rsa *.csv cloudera@192.168.47.129:/home/cloudera/data/
```

Mot de passe : `cloudera`

### Sur la VM — Créer les tables et charger les données

Connecte-toi à Beeline :

```bash
beeline -u "jdbc:hive2://localhost:10000/default" -n cloudera
```

Colle ce SQL en une seule fois :

```sql
CREATE DATABASE IF NOT EXISTS ecommerce;
USE ecommerce;

CREATE TABLE IF NOT EXISTS customers (
  customer_id INT, full_name STRING, email STRING,
  country STRING, city STRING, signup_date STRING,
  age INT, gender STRING
) ROW FORMAT DELIMITED FIELDS TERMINATED BY ','
STORED AS TEXTFILE TBLPROPERTIES ("skip.header.line.count"="1");

CREATE TABLE IF NOT EXISTS products (
  product_id INT, product_name STRING, category STRING,
  sub_category STRING, brand STRING, unit_price DOUBLE, stock_qty INT
) ROW FORMAT DELIMITED FIELDS TERMINATED BY ','
STORED AS TEXTFILE TBLPROPERTIES ("skip.header.line.count"="1");

CREATE TABLE IF NOT EXISTS orders (
  order_id INT, customer_id INT, order_date STRING,
  status STRING, payment_method STRING,
  shipping_country STRING, total_amount DOUBLE
) ROW FORMAT DELIMITED FIELDS TERMINATED BY ','
STORED AS TEXTFILE TBLPROPERTIES ("skip.header.line.count"="1");

CREATE TABLE IF NOT EXISTS order_items (
  item_id INT, order_id INT, product_id INT,
  quantity INT, unit_price DOUBLE,
  discount_pct DOUBLE, subtotal DOUBLE
) ROW FORMAT DELIMITED FIELDS TERMINATED BY ','
STORED AS TEXTFILE TBLPROPERTIES ("skip.header.line.count"="1");

CREATE TABLE IF NOT EXISTS reviews (
  review_id INT, order_id INT, product_id INT,
  customer_id INT, rating INT,
  review_date STRING, comment STRING
) ROW FORMAT DELIMITED FIELDS TERMINATED BY ','
STORED AS TEXTFILE TBLPROPERTIES ("skip.header.line.count"="1");

LOAD DATA LOCAL INPATH '/home/cloudera/data/customers.csv'   OVERWRITE INTO TABLE customers;
LOAD DATA LOCAL INPATH '/home/cloudera/data/products.csv'    OVERWRITE INTO TABLE products;
LOAD DATA LOCAL INPATH '/home/cloudera/data/orders.csv'      OVERWRITE INTO TABLE orders;
LOAD DATA LOCAL INPATH '/home/cloudera/data/order_items.csv' OVERWRITE INTO TABLE order_items;
LOAD DATA LOCAL INPATH '/home/cloudera/data/reviews.csv'     OVERWRITE INTO TABLE reviews;
```

### Vérification

```sql
SHOW TABLES;
SELECT COUNT(*) FROM orders;  
```

---

##  Étape 3 — Lancer le Backend FastAPI *(PowerShell 1)*

```powershell
cd C:\Users\HP\Desktop\ecommerce-dashboard\backend

# 1ère fois seulement
pip install -r requirements.txt
copy .env.example .env
notepad .env        # → remplacer GEMINI_API_KEY=YOUR_GEMINI_API_KEY_HERE
                    #   par ta vraie clé : https://aistudio.google.com/apikey

# Lancer le serveur
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Résultat attendu :
```
INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     Application startup complete.
```

Vérification dans le navigateur : http://localhost:8000/api/health
→ doit afficher `{"status":"ok"}`

---

##  Étape 4 — Lancer le Frontend React *(PowerShell 2)*

```powershell
cd C:\Users\HP\Desktop\ecommerce-dashboard\frontend

# 1ère fois seulement
copy .env.example .env
npm install

# Lancer l'application
npm start
```

Le navigateur s'ouvre automatiquement sur **http://localhost:3000**

| Champ | Valeur |
|-------|--------|
| Login | `admin` |
| Mot de passe | `admin123` |

---

##  Dépannage

### Hive ne démarre pas après redémarrage de la VM

Reprendre l'étape 1 dans l'ordre exact. Si le port 10000 n'est toujours pas ouvert :

```bash
sudo service hive-server2 stop
sudo service hive-metastore stop
sleep 5
sudo service hive-metastore start
sleep 20
sudo service hive-server2 start
sudo netstat -tlnp | grep 10000
```

### Erreur SSH "no matching host key type"

Toujours utiliser `-oHostKeyAlgorithms=+ssh-rsa` pour SSH et SCP :

```powershell
ssh -oHostKeyAlgorithms=+ssh-rsa cloudera@192.168.47.129
```


