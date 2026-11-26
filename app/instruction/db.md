
# base de donnees


erDiagram
    USER_ADMIN {
        bigint id PK
        string email UK
        string nom
        string prenom
        string password_hash
        string role_admin
    }
    LANGUE {
        bigint id PK
        string code UK
        string nom UK
    }
    USER_ADMIN_LANGUE {
        bigint user_admin_id PK,FK
        bigint langue_id PK,FK
    }
    SOCIETE {
        bigint id PK
        string nom
        bigint createur_id FK
        bigint type_societe_id FK
        string statut
    }
    TYPE_SOCIETE {
        bigint id PK
        string nom UK
    }
    SOCIETE_DOCUMENT {
        bigint id PK
        bigint societe_id FK
        string type_document
        string fichier
    }
    ROLE {
        bigint id PK
        bigint societe_id FK
        string nom
    }
    PERMISSION {
        bigint id PK
        string code UK
        string module
    }
    ROLE_PERMISSION {
        bigint role_id PK,FK
        bigint permission_id PK,FK
    }
    PERMISSION_SOCIETE {
        bigint id PK
        bigint societe_id FK
        bigint permission_id FK
        string source
    }
    FONCTION {
        bigint id PK
        bigint societe_id FK
        string nom
    }
    EMPLOYE {
        bigint id PK
        bigint societe_id FK
        string nom
        string prenom
        bigint role_id FK
        bigint fonction_id FK
    }
    EMPLOYE_LANGUE {
        bigint employe_id PK,FK
        bigint langue_id PK,FK
    }
    TYPE_CONTRAT {
        bigint id PK
        string code UK
    }
    CONTRAT_EMPLOYE {
        bigint id PK
        bigint employe_id FK
        bigint type_contrat_id FK
        decimal salaire_contractuel
    }
    PAIEMENT_SALAIRE {
        bigint id PK
        bigint employe_id FK
        bigint contrat_id FK
        decimal montant_paye
    }

    USER_ADMIN ||--o{ USER_ADMIN_LANGUE : "parle"
    LANGUE ||--o{ USER_ADMIN_LANGUE : ""
    USER_ADMIN ||--|{ SOCIETE : "crée"
    TYPE_SOCIETE ||--o{ SOCIETE : "catégorise"
    SOCIETE ||--|{ SOCIETE_DOCUMENT : "possède"
    SOCIETE ||--|{ ROLE : "définit"
    SOCIETE ||--|{ FONCTION : "définit"
    ROLE ||--o{ ROLE_PERMISSION : "détient"
    PERMISSION ||--o{ ROLE_PERMISSION : ""
    SOCIETE ||--o{ PERMISSION_SOCIETE : "active"
    PERMISSION ||--o{ PERMISSION_SOCIETE : ""
    SOCIETE ||--|{ EMPLOYE : "emploie"
    EMPLOYE ||--o{ EMPLOYE_LANGUE : "parle"
    EMPLOYE }o--|| ROLE : "possède"
    EMPLOYE }o--|| FONCTION : "occupe"
    EMPLOYE ||--|{ CONTRAT_EMPLOYE : "historique"
    TYPE_CONTRAT ||--|{ CONTRAT_EMPLOYE : ""
    EMPLOYE ||--|{ PAIEMENT_SALAIRE : "perçoit"
    CONTRAT_EMPLOYE ||--o{ PAIEMENT_SALAIRE : "justifie"