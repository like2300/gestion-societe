import os

from allauth.account.forms import SignupForm as AllauthSignupForm
from django import forms
from django.urls import reverse_lazy
from django.utils import timezone

from . import geographie
from .models import (
    COULEUR_SOCIETE_CHOICES,
    Client,
    ContratEmploye,
    DemandeAdhesion,
    DepenseSociete,
    EcheancePaiement,
    Employe,
    Finance,
    Fonction,
    ModePaiement,
    PaiementClient,
    PaiementSalaire,
    ProjetChef,
    ProjetClient,
    ProspectionClient,
    Reunion,
    Role,
    SOURCE_CLIENT_CHOICES,
    Societe,
    SocieteDocument,
    TypeContrat,
    TypeClient,
    TypeDepense,
    UserAdmin,
)

# ---------------------------------------------------------------------------
# Sélecteur enrichi (composant réutilisable, rendu par static/gestion/search-select.js)
# Chaque <option> peut porter : data-sub (2e ligne), data-meta (étiquette à droite),
# data-color (pastille), data-parent (valeur du champ parent, cf. data-depends-on sur
# le <select>) et data-fill (JSON {nom_du_champ: valeur} pré-rempli au choix).
# ---------------------------------------------------------------------------

class RichSelect(forms.Select):
    def __init__(self, *args, options_attrs=None, **kwargs):
        self.options_attrs = options_attrs
        super().__init__(*args, **kwargs)

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex=subindex, attrs=attrs)
        if self.options_attrs and value not in ("", None):
            cible = getattr(value, "instance", None)
            extra = self.options_attrs(cible if cible is not None else value) or {}
            for cle, val in extra.items():
                if val in (None, ""):
                    continue
                if cle == "fill":
                    import json
                    val = json.dumps(val)
                option["attrs"]["data-" + cle] = str(val)
        return option


def enrichir(form, nom, options_attrs=None, **attrs):
    """Transforme le champ « nom » en sélecteur enrichi (recherche + suggestions contextuelles)."""
    champ = form.fields[nom]
    widget_attrs = {"data-searchable": "", **{k.replace("_", "-"): v for k, v in attrs.items()}}
    champ.widget = RichSelect(attrs=widget_attrs, options_attrs=options_attrs)
    if hasattr(champ, "queryset"):
        champ.queryset = champ.queryset  # recopie les choix dans le nouveau widget
    else:
        champ.choices = champ.choices


def _fcfa(v):
    try:
        return f"{int(round(float(v or 0))):,} FCFA".replace(",", " ")
    except (TypeError, ValueError):
        return ""


COULEURS_STATUT_PAIEMENT = {"CONFIRME": "#10b981", "EN_ATTENTE": "#f59e0b", "ANNULE": "#e11d48"}


class SignupFormPro(AllauthSignupForm):
    """Formulaire d'inscription : seuls les administrateurs d'entreprise
    s'inscrivent eux-mêmes.

    Les comptes employés ne se créent plus ici : c'est l'administrateur de la
    société qui crée la fiche employé (le compte de connexion est alors généré
    avec un mot de passe par défaut, à personnaliser à la première connexion).
    """

    field_order = ["email", "password1", "password2"]


class SocieteConfigForm(forms.ModelForm):
    """Modification des informations de la société + personnalisation du dashboard."""

    logo = forms.ImageField(
        required=False,
        label="Logo de la société",
        help_text="Images : PNG, JPG, JPEG, WEBP, GIF, SVG. Laissez vide pour conserver l'actuel.",
    )

    ALLOWED_LOGO_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}

    class Meta:
        model = Societe
        fields = ["nom", "pays", "slogan", "couleur", "modes_paiement"]
        widgets = {
            "slogan": forms.TextInput(attrs={"placeholder": "Facultatif"}),
            "modes_paiement": forms.CheckboxSelectMultiple,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["modes_paiement"].queryset = ModePaiement.objects.filter(
            actif=True
        )
        self.fields["modes_paiement"].required = False
        self.fields["modes_paiement"].label = "Modes de paiement disponibles"
        self.fields["modes_paiement"].help_text = (
            "Cochez uniquement les modes que votre société utilise vraiment : "
            "ils seront proposés pour payer les salaires."
        )
        # Champs « style Google » : libellé flottant (placeholder vide requis par le CSS).
        for nom in ("nom", "pays", "slogan"):
            self.fields[nom].widget.attrs.update({"placeholder": " ", "class": "gf-input", "autocomplete": "off"})
        self.fields["logo"].widget.attrs.update({"accept": "image/*", "class": "dz-input"})

    def clean_logo(self):
        logo = self.cleaned_data.get("logo")
        if logo:
            ext = os.path.splitext(logo.name)[1].lower()
            if ext not in self.ALLOWED_LOGO_EXTS:
                raise forms.ValidationError(
                    "Le logo doit être une image (PNG, JPG, JPEG, WEBP, GIF, SVG)."
                )
        return logo


class SocieteCreationForm(forms.Form):
    """Étape de création de la première société : infos + logo + documents PDF."""

    nom = forms.CharField(label="Nom de la société", max_length=200)
    pays = forms.CharField(label="Pays", max_length=100)
    slogan = forms.CharField(label="Slogan", required=False, max_length=255)
    couleur = forms.ChoiceField(
        label="Couleur du dashboard",
        choices=COULEUR_SOCIETE_CHOICES,
        initial="SKY",
    )
    logo = forms.FileField(label="Logo de la société")
    document = forms.FileField(label="Documents de la société (PDF)")

    ALLOWED_LOGO_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}
    ALLOWED_DOC_EXTS = {".pdf"}

    def clean_logo(self):
        logo = self.cleaned_data.get("logo")
        if logo:
            ext = os.path.splitext(logo.name)[1].lower()
            if ext not in self.ALLOWED_LOGO_EXTS:
                raise forms.ValidationError(
                    "Le logo doit être une image (PNG, JPG, JPEG, WEBP, GIF, SVG)."
                )
        return logo

    def clean_document(self):
        document = self.cleaned_data.get("document")
        if document:
            ext = os.path.splitext(document.name)[1].lower()
            if ext not in self.ALLOWED_DOC_EXTS:
                raise forms.ValidationError(
                    "Le document de la société doit être un PDF."
                )
        return document


class UserProfilForm(forms.ModelForm):
    """Modification du profil de l'utilisateur connecté + photo de profil."""

    photo_profil = forms.ImageField(
        required=False,
        label="Photo de profil",
        help_text=(
            "Images : PNG, JPG, JPEG, GIF (max 5 Mo). "
            "Laissez vide pour conserver la photo actuelle."
        ),
    )

    ALLOWED_PHOTO_EXTS = {".png", ".jpg", ".jpeg", ".gif"}

    class Meta:
        model = UserAdmin
        fields = [
            "email",
            "prenom",
            "nom",
            "telephone_1",
            "telephone_2",
            "date_naissance",
            "lieu_naissance",
            "nationalite",
            "numero_piece_identite",
        ]
        widgets = {
            "email": forms.EmailInput(attrs={"placeholder": "ex: nom@domaine.com"}),
            "date_naissance": forms.DateInput(
                attrs={"type": "date", "max": "2100-12-31"},
                format="%Y-%m-%d",
            ),
        }
        labels = {
            "email": "Adresse e-mail",
            "prenom": "Prénom",
            "nom": "Nom",
            "telephone_1": "Téléphone principal",
            "telephone_2": "Téléphone secondaire",
            "date_naissance": "Date de naissance",
            "lieu_naissance": "Lieu de naissance",
            "nationalite": "Nationalité",
            "numero_piece_identite": "N° pièce d'identité",
        }
        help_texts = {
            "email": "Utilisé pour vous connecter à la plateforme.",
            "numero_piece_identite": "Carte d'identité, passeport, permis…",
        }

    def clean_photo_profil(self):
        photo = self.cleaned_data.get("photo_profil")
        if photo:
            if photo.size > 5 * 1024 * 1024:
                raise forms.ValidationError("La photo ne doit pas dépasser 5 Mo.")
            ext = os.path.splitext(photo.name)[1].lower()
            if ext not in self.ALLOWED_PHOTO_EXTS:
                raise forms.ValidationError(
                    "La photo doit être une image (PNG, JPG, JPEG, GIF)."
                )
        return photo


class EmployeChoiceField(forms.ModelChoiceField):
    """Choix d'un employé avec un libellé « Prénom Nom · Fonction »."""

    def label_from_instance(self, obj):
        label = f"{obj.prenom} {obj.nom}".strip()
        if obj.fonction_id:
            label = f"{label} · {obj.fonction.nom}"
        return label


class FonctionChoiceField(forms.ModelChoiceField):
    """Choix d'une fonction avec un libellé simple (sans le groupe société)."""

    def label_from_instance(self, obj):
        return obj.nom


class EmployeForm(forms.ModelForm):
    """Création / modification d'un employé dans le dashboard."""

    logo = forms.ImageField(
        required=False,
        label="Photo de profil",
        help_text="Images : PNG, JPG, JPEG, WEBP, GIF, SVG.",
    )
    document = forms.FileField(
        required=False,
        label="Document de l'employé",
        help_text="Facultatif : ajoute un document (PDF, image…).",
    )
    contrat_type = forms.ModelChoiceField(
        queryset=TypeContrat.objects.all(),
        required=False,
        label="Type de contrat",
        help_text="Facultatif : crée le premier contrat de l'employé.",
    )
    contrat_date_debut = forms.DateField(
        required=False,
        label="Début du contrat",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    contrat_date_fin = forms.DateField(
        required=False,
        label="Fin du contrat (CDD)",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    contrat_salaire = forms.DecimalField(
        required=False,
        label="Salaire contractuel",
        widget=forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
    )
    contrat_lieu_travail = forms.CharField(
        required=False, max_length=255, label="Lieu de travail",
        help_text="Par défaut : adresse de la société.",
    )
    contrat_heures_hebdo = forms.IntegerField(
        required=False, min_value=1, max_value=80, initial=40, label="Heures par semaine",
    )
    contrat_periode_essai = forms.IntegerField(
        required=False, min_value=0, max_value=365, label="Période d'essai (jours)",
        help_text="Vide : valeur usuelle selon le type de contrat.",
    )
    contrat_missions = forms.CharField(
        required=False, label="Missions principales",
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Une mission par ligne"}),
    )
    fonction = FonctionChoiceField(
        queryset=Fonction.objects.none(),
        required=False,
        label="Fonction",
    )

    class Meta:
        model = Employe
        fields = [
            "nom",
            "prenom",
            "date_naissance",
            "lieu_naissance",
            "nationalite",
            "numero_piece_identite",
            "adresse",
            "telephone_1",
            "telephone_2",
            "email",
            "salaire",
            "fonction",
            "statut",
            "date_recrutement",
            "jour_paiement",
        ]
        widgets = {
            "date_naissance": forms.DateInput(attrs={"type": "date"}),
            "date_recrutement": forms.DateInput(attrs={"type": "date"}),
            "salaire": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
        }

    ALLOWED_DOC_EXTS = {
        ".pdf",
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".gif",
        ".doc",
        ".docx",
        ".odt",
        ".xls",
        ".xlsx",
        ".ods",
        ".txt",
    }

    def __init__(self, *args, societe=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].required = False
        self.fields["fonction"].empty_label = "— Aucune fonction —"
        self.fields["fonction"].widget.attrs["data-create-url"] = reverse_lazy(
            "gestion:fonction_creer"
        )
        self.fields["fonction"].widget.attrs["data-create-label"] = "Créer une fonction"
        self.fields["fonction"].widget.attrs["data-create-title"] = "Nouvelle fonction"
        self.fields["fonction"].widget.attrs["data-create-subtitle"] = (
            "La fonction sera ajoutée à la liste des fonctions."
        )
        if societe:
            self.fields["fonction"].queryset = Fonction.objects.filter(
                societe=societe
            ).order_by("nom")
        self.fields["contrat_type"].empty_label = "— Type de contrat —"
        self.fields["contrat_type"].help_text = "Le contrat de travail est généré automatiquement (CDI par défaut)."
        # En modification : pré-remplit la section contrat avec le contrat en cours
        contrat = self.instance.contrats.filter(statut="ACTIF").first() if self.instance.pk else None
        if contrat and not self.is_bound:
            self.initial.update({
                "contrat_type": contrat.type_contrat_id, "contrat_date_debut": contrat.date_debut,
                "contrat_date_fin": contrat.date_fin, "contrat_salaire": contrat.salaire_contractuel,
                "contrat_lieu_travail": contrat.lieu_travail, "contrat_heures_hebdo": contrat.heures_hebdo,
                "contrat_periode_essai": contrat.periode_essai_jours, "contrat_missions": contrat.missions,
            })

    def clean(self):
        donnees = super().clean()
        t = donnees.get("contrat_type")
        if t and t.code in ("CDD", "STAGE") and not donnees.get("contrat_date_fin"):
            self.add_error("contrat_date_fin", "Indiquez la date de fin pour un CDD ou un stage.")
        debut, fin = donnees.get("contrat_date_debut"), donnees.get("contrat_date_fin")
        if debut and fin and fin < debut:
            self.add_error("contrat_date_fin", "La fin du contrat doit suivre son début.")
        return donnees

    def clean_document(self):
        document = self.cleaned_data.get("document")
        if document:
            ext = os.path.splitext(document.name)[1].lower()
            if ext not in self.ALLOWED_DOC_EXTS:
                raise forms.ValidationError(
                    "Format de document non autorisé (PDF, image ou document bureautique)."
                )
        return document


class ClientForm(forms.ModelForm):
    """Création / modification d'un client dans le dashboard."""

    logo = forms.ImageField(
        required=False,
        label="Logo du client",
        help_text="Images : PNG, JPG, JPEG, WEBP, GIF, SVG.",
    )
    document = forms.FileField(
        required=False,
        label="Document du client (PDF)",
        help_text="Facultatif : crée un document client.",
    )
    responsable = EmployeChoiceField(
        queryset=Employe.objects.none(),
        required=False,
        label="Responsable du client",
        help_text="Employé en charge du suivi de ce client.",
    )
    source = forms.ChoiceField(
        required=False,
        label="Source du client",
        choices=[("", "— Choisir une source —")] + list(SOURCE_CLIENT_CHOICES),
    )
    pays = forms.ChoiceField(
        required=False,
        label="Pays",
        help_text="Le client apparaît sur la carte du monde (Globe) d'après son pays et sa ville.",
    )

    ALLOWED_LOGO_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}
    ALLOWED_DOC_EXTS = {".pdf"}

    class Meta:
        model = Client
        fields = [
            "nom",
            "type_client",
            "source",
            "responsable",
            "email",
            "telephone_1",
            "telephone_2",
            "adresse",
            "ville",
            "pays",
            "statut",
        ]
        widgets = {
            "telephone_1": forms.TextInput(),
            "telephone_2": forms.TextInput(attrs={"placeholder": "Facultatif"}),
        }

    def __init__(self, *args, societe=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["type_client"].queryset = TypeClient.objects.all().order_by("nom")
        self.fields["type_client"].empty_label = "— Choisir un type —"
        self.fields["type_client"].widget.attrs["data-create-url"] = reverse_lazy(
            "gestion:type_client_creer"
        )
        self.fields["type_client"].widget.attrs["data-create-label"] = "Créer un type de client"
        self.fields["type_client"].widget.attrs["data-create-title"] = "Nouveau type de client"
        if societe:
            self.fields["responsable"].queryset = (
                Employe.objects.filter(societe=societe)
                .select_related("fonction")
                .order_by("nom", "prenom")
            )
            self.fields["responsable"].empty_label = "— Aucun employé —"
        # Pays : liste déroulante (noms reconnus par la carte du monde) ;
        # par défaut le pays de la société pour un nouveau client.
        actuel = (self.data.get(self.add_prefix("pays")) if self.is_bound else None) or (
            self.instance.pays if self.instance and self.instance.pk else ""
        )
        if actuel and geographie.est_connu(actuel):
            actuel_aff = geographie.nom_fr(actuel)
        else:
            actuel_aff = actuel or ""
        self.fields["pays"].choices = geographie.choix_pays(actuel_aff)
        if self.instance and self.instance.pk:
            self.initial["pays"] = actuel_aff
        elif societe and getattr(societe, "pays", ""):
            self.initial["pays"] = geographie.nom_fr(societe.pays)
        self.fields["pays"].widget.attrs["data-searchable"] = ""
        self.fields["pays"].widget.attrs["data-pays-defaut"] = (
            geographie.nom_fr(societe.pays) if societe and getattr(societe, "pays", "") else ""
        )
        self.fields["ville"].widget.attrs.update({
            "list": "villes-connues",
            "autocomplete": "off",
            "placeholder": "Ex. Brazzaville",
        })
        self.fields["ville"].help_text = "Les villes proposées sont placées précisément sur la carte."

    def clean_pays(self):
        return (self.cleaned_data.get("pays") or "").strip()

    def clean_logo(self):
        logo = self.cleaned_data.get("logo")
        if logo:
            ext = os.path.splitext(logo.name)[1].lower()
            if ext not in self.ALLOWED_LOGO_EXTS:
                raise forms.ValidationError(
                    "Le logo doit être une image (PNG, JPG, JPEG, WEBP, GIF, SVG)."
                )
        return logo

    def clean_document(self):
        document = self.cleaned_data.get("document")
        if document:
            ext = os.path.splitext(document.name)[1].lower()
            if ext not in self.ALLOWED_DOC_EXTS:
                raise forms.ValidationError("Le document doit être un PDF.")
        return document


class ProspectionForm(forms.ModelForm):
    """Prospect du pipeline commercial (module Prospection).

    ``responsable`` est restreint aux employés de la société. La conversion
    d'un prospect gagné en fiche client se déclenche via ``convertir_en_client``
    (cocher en complétant ``type_client``) : elle crée le ``Client`` lié et
    bascule le statut sur « Gagné ».
    """

    responsable = forms.ModelChoiceField(
        queryset=Employe.objects.none(),
        required=False,
        label="Responsable",
        help_text="Commercial en charge de ce prospect.",
    )
    convertir_en_client = forms.BooleanField(
        required=False,
        label="Convertir en client",
        help_text="Crée la fiche client liée (statut du prospect → Gagné).",
    )
    type_client = forms.ModelChoiceField(
        queryset=TypeClient.objects.none(),
        required=False,
        label="Type de client",
        help_text="Obligatoire pour convertir.",
    )

    class Meta:
        model = ProspectionClient
        fields = [
            "nom",
            "contact",
            "source",
            "responsable",
            "email",
            "telephone",
            "ville",
            "pays",
            "budget_estime",
            "statut",
            "date_prospection",
            "description",
            "convertir_en_client",
            "type_client",
        ]
        widgets = {
            "date_prospection": forms.DateInput(attrs={"type": "date"}),
            "budget_estime": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
        }

    def __init__(self, *args, societe=None, **kwargs):
        super().__init__(*args, **kwargs)
        if societe:
            self.fields["responsable"].queryset = Employe.objects.filter(
                societe=societe
            ).order_by("nom", "prenom")
            self.fields["responsable"].empty_label = "— Aucun employé —"
            self.fields["type_client"].queryset = TypeClient.objects.all().order_by("nom")
            self.fields["type_client"].empty_label = "— Choisir un type —"

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("convertir_en_client") and not cleaned.get("type_client"):
            self.add_error(
                "type_client",
                "Un type de client est requis pour convertir le prospect.",
            )
        return cleaned


class ReunionForm(forms.ModelForm):
    """Programmation d'une réunion interne avec lien Google Meet.

    ``participants`` est restreint aux employés de la société ; la durée se
    choisit dans une liste (30 min à 2 h, 1 h par défaut).
    """

    class Meta:
        model = Reunion
        fields = ["titre", "date", "heure", "duree", "participants", "description"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "heure": forms.TimeInput(attrs={"type": "time"}),
            "duree": forms.Select(attrs={"class": "meet-duree"}),
            "description": forms.Textarea(attrs={"rows": 2, "placeholder": "Ordre du jour (optionnel)…"}),
            "titre": forms.TextInput(attrs={"placeholder": "Ex. : Point hebdo équipe"}),
        }

    def __init__(self, *args, societe=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["participants"].required = True
        self.fields["participants"].label = "Participants"
        self.fields["participants"].help_text = "Choisir un ou plusieurs employés."
        if societe is not None:
            self.fields["participants"].queryset = Employe.objects.filter(
                societe=societe
            ).order_by("nom", "prenom")
        self.fields["participants"].label_from_instance = lambda obj: (
            f"{obj.prenom} {obj.nom}".strip()
        )

    def clean(self):
        cleaned = super().clean()
        date = cleaned.get("date")
        heure = cleaned.get("heure")
        if date and heure and (date, heure) < (
            timezone.localdate(), timezone.localtime().time()
        ):
            self.add_error("heure", "La réunion doit être programmée dans le futur.")
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        if not instance.duree:
            instance.duree = 60
        if commit:
            instance.save()
            self.save_m2m()
        return instance


class ClientChoiceField(forms.ModelChoiceField):
    """Choix d'un client avec un libellé simple (nom seul)."""

    def label_from_instance(self, obj):
        return obj.nom


class ProjetForm(forms.ModelForm):
    """Création / modification d'un projet dans le dashboard.

    ``responsable`` est l'employé **en charge** du projet : une seule fiche de
    chef de projet « principal » est conservée (``ProjetChef.principal``),
    remplacée à chaque modification.
    """

    client = ClientChoiceField(
        queryset=Client.objects.none(),
        label="Client",
    )
    responsable = EmployeChoiceField(
        queryset=Employe.objects.none(),
        required=False,
        label="Responsable",
        help_text="Employé en charge de ce projet.",
    )

    class Meta:
        model = ProjetClient
        fields = [
            "responsable",
            "client",
            "nom",
            "description",
            "date_debut",
            "date_fin",
            "budget",
            "statut",
        ]
        widgets = {
            "date_debut": forms.DateInput(attrs={"type": "date"}),
            "date_fin": forms.DateInput(attrs={"type": "date"}),
            "budget": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
        }

    def __init__(self, *args, societe=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["client"].empty_label = "— Choisir un client —"
        self.fields["responsable"].empty_label = "— Aucun employé —"
        if societe:
            self.fields["client"].queryset = Client.objects.filter(
                societe=societe
            ).order_by("nom")
            self.fields["responsable"].queryset = Employe.objects.filter(
                societe=societe
            ).select_related("fonction").order_by("nom", "prenom")
        if self.instance and self.instance.pk:
            chef = self.instance.chefs.filter(principal=True).first()
            if chef is not None:
                self.fields["responsable"].initial = chef.employe_id

    def save(self, commit=True):
        projet = super().save(commit=commit)
        if commit:
            self._maj_responsable(projet)
        return projet

    def _maj_responsable(self, projet):
        """Synchronise le chef de projet principal avec le champ responsable.

        Un seul principal par projet ; si l'employé possède déjà une fiche
        (même non-principale), elle est promue au lieu d'être dupliquée à cause
        de l'unicité (projet, employé).
        """
        resp = self.cleaned_data.get("responsable")
        actuel = projet.chefs.filter(principal=True).first()
        if resp is None:
            if actuel is not None:
                actuel.delete()
            return
        if actuel is not None and actuel.employe_id == resp.pk:
            return
        ligne = projet.chefs.filter(employe_id=resp.pk).first()
        if actuel is not None:
            actuel.delete()
        if ligne is None:
            ligne = ProjetChef.objects.create(
                projet=projet,
                employe=resp,
                date_affectation=timezone.localdate(),
            )
        ligne.principal = True
        ligne.date_affectation = timezone.localdate()
        ligne.save()


class FinanceForm(forms.ModelForm):
    """Synthèse financière mensuelle."""

    class Meta:
        model = Finance
        fields = ["periode", "total_recettes", "total_depenses", "solde"]
        widgets = {
            "periode": forms.DateInput(attrs={"type": "date"}),
            "total_recettes": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "total_depenses": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "solde": forms.NumberInput(attrs={"step": "0.01"}),
        }

    def __init__(self, *args, societe=None, **kwargs):
        super().__init__(*args, **kwargs)


class DepenseForm(forms.ModelForm):
    """Dépenses de la société."""

    class Meta:
        model = DepenseSociete
        fields = [
            "type_depense",
            "nom",
            "montant",
            "date_depense",
            "description",
            "statut",
            "employe",
            "periode_mois",
        ]
        widgets = {
            "date_depense": forms.DateInput(attrs={"type": "date"}),
            "periode_mois": forms.DateInput(attrs={"type": "date"}),
            "montant": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, societe=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["type_depense"].queryset = TypeDepense.objects.all()
        self.fields["employe"].required = False
        self.fields["employe"].label = "Employé"
        self.fields["employe"].help_text = (
            "Pour le type « Salaires » : l'employé concerné, le paiement est "
            "créé / synchronisé dans la page Salaires."
        )
        self.fields["periode_mois"].required = False
        self.fields["periode_mois"].label = "Période (mois)"
        if societe:
            self.fields["employe"].queryset = Employe.objects.filter(
                societe=societe
            ).order_by("nom", "prenom")


class SalaireForm(forms.ModelForm):
    """Paiement de salaire."""

    class Meta:
        model = PaiementSalaire
        fields = [
            "employe",
            "contrat",
            "periode_mois",
            "montant_du",
            "montant_paye",
            "date_prevue",
            "date_paiement",
            "mode_paiement",
            "statut",
        ]
        widgets = {
            "periode_mois": forms.DateInput(attrs={"type": "date"}),
            "date_prevue": forms.DateInput(attrs={"type": "date"}),
            "date_paiement": forms.DateInput(attrs={"type": "date"}),
            "montant_du": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "montant_paye": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
        }

    def __init__(self, *args, societe=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["contrat"].required = False
        self.fields["date_paiement"].required = False
        self.fields["mode_paiement"].required = False
        # Flux « prévu d'abord » : ces champs deviennent facultatifs, ils sont
        # remplis automatiquement (montant dû = contrat/fiche, payé = 0) et le
        # paiement se valide ensuite via le bouton ✓ de la liste.
        self.fields["montant_du"].required = False
        self.fields["montant_paye"].required = False
        self.fields["date_prevue"].required = False
        self.fields["statut"].required = False  # forcé côté vue (prévu d'abord)
        self.fields["statut"].help_text = (
            "Un salaire créé ici est toujours « Prévu » ; il devient « Payé » "
            "via le bouton ✓ de la liste (et génère la dépense automatiquement)."
        )
        if societe:
            self.fields["employe"].queryset = Employe.objects.filter(societe=societe)
            self.fields["contrat"].queryset = ContratEmploye.objects.filter(
                employe__societe=societe
            )
            modes = societe.modes_paiement.filter(actif=True)
            if modes.exists():
                self.fields["mode_paiement"].queryset = modes
                self.fields["mode_paiement"].help_text = (
                    "Modes activés dans la configuration de votre société "
                    '(« Ma société » → « Configurer la société »).'
                )
            else:
                self.fields["mode_paiement"].queryset = ModePaiement.objects.all()
                self.fields["mode_paiement"].help_text = (
                    "Aucun mode configuré pour la société : tous les modes actifs "
                    "sont proposés. Configurez-les dans « Ma société » ."
                )


class ContratForm(forms.ModelForm):
    """Contrat de travail."""

    class Meta:
        model = ContratEmploye
        fields = [
            "employe",
            "type_contrat",
            "date_debut",
            "date_fin",
            "salaire_contractuel",
            "statut",
        ]
        widgets = {
            "date_debut": forms.DateInput(attrs={"type": "date"}),
            "date_fin": forms.DateInput(attrs={"type": "date"}),
            "salaire_contractuel": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
        }

    def __init__(self, *args, societe=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["date_fin"].required = False
        self.fields["type_contrat"].queryset = TypeContrat.objects.all()
        if societe:
            self.fields["employe"].queryset = Employe.objects.filter(societe=societe)


class EcheanceForm(forms.ModelForm):
    """Échéance de paiement d'un projet."""

    class Meta:
        model = EcheancePaiement
        fields = ["projet", "numero_echeance", "montant_prevu", "date_prevue", "statut"]
        widgets = {
            "date_prevue": forms.DateInput(attrs={"type": "date"}),
            "montant_prevu": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
        }

    def __init__(self, *args, societe=None, **kwargs):
        super().__init__(*args, **kwargs)
        if societe:
            self.fields["projet"].queryset = ProjetClient.objects.filter(societe=societe)


class PaiementForm(forms.ModelForm):
    """Paiement client."""

    class Meta:
        model = PaiementClient
        fields = [
            "projet",
            "echeance",
            "montant",
            "date_paiement",
            "mode_paiement",
            "reference",
            "statut",
        ]
        widgets = {
            "date_paiement": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "montant": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
        }
        labels = {
            "echeance": "Échéance", "montant": "Montant (FCFA)", "date_paiement": "Date du paiement",
            "mode_paiement": "Mode de paiement", "reference": "Référence",
        }

    def __init__(self, *args, societe=None, **kwargs):
        super().__init__(*args, **kwargs)
        from django.db.models import Q, Sum

        self.fields["echeance"].required = False
        self.fields["reference"].required = False
        self.fields["mode_paiement"].queryset = ModePaiement.objects.filter(actif=True)
        if societe:
            projets = (ProjetClient.objects.filter(societe=societe).select_related("client")
                       .annotate(encaisse=Sum("paiements__montant", filter=Q(paiements__statut="CONFIRME"))))
            self.fields["projet"].queryset = projets
            self.fields["echeance"].queryset = (
                EcheancePaiement.objects.filter(projet__societe=societe).select_related("projet")
                .annotate(encaisse=Sum("paiements__montant", filter=Q(paiements__statut="CONFIRME")))
                .order_by("projet__nom", "numero_echeance")
            )
        else:
            self.fields["projet"].queryset = ProjetClient.objects.none()
            self.fields["echeance"].queryset = EcheancePaiement.objects.none()

        def projet_attrs(p):
            reste = float(p.budget or 0) - float(getattr(p, "encaisse", 0) or 0)
            return {
                "sub": f"{p.client.nom if p.client_id else 'Sans client'} · budget {_fcfa(p.budget)}",
                "meta": f"Reste {_fcfa(reste)}" if reste > 0 else "Soldé",
            }

        def echeance_attrs(e):
            du = float(e.montant_prevu or 0)
            reste = max(du - float(getattr(e, "encaisse", 0) or 0), 0)
            return {
                "sub": f"Prévue le {e.date_prevue:%d/%m/%Y} · {e.get_statut_display()}",
                "meta": _fcfa(reste) if reste else "Payée",
                "parent": e.projet_id,
                "color": {"RETARD": "#e11d48", "PARTIELLE": "#f59e0b", "PAYEE": "#10b981"}.get(e.statut, "#3b82f6"),
                "fill": {"montant": f"{reste:.0f}"} if reste else None,
            }

        enrichir(self, "projet", projet_attrs)
        enrichir(self, "echeance", echeance_attrs, data_depends_on="projet",
                 data_depends_label="Choisissez d'abord un projet")
        self.fields["projet"].label_from_instance = lambda p: p.nom
        self.fields["echeance"].label_from_instance = lambda e: f"Échéance n° {e.numero_echeance} — {e.projet.nom}"
        self.fields["echeance"].empty_label = "Paiement libre (sans échéance)"
        enrichir(self, "mode_paiement", lambda m: {"sub": m.code})
        enrichir(self, "statut", lambda v: {"color": COULEURS_STATUT_PAIEMENT.get(str(v))})
        if not self.instance.pk:
            self.initial.setdefault("statut", "CONFIRME")
            self.initial.setdefault("date_paiement", timezone.localdate())


class RoleForm(forms.ModelForm):
    """Rôle interne."""

    class Meta:
        model = Role
        fields = ["nom", "description", "statut"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, societe=None, **kwargs):
        super().__init__(*args, **kwargs)


class FonctionForm(forms.ModelForm):
    """Fonction / poste."""

    class Meta:
        model = Fonction
        fields = ["nom", "description", "actif"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, societe=None, **kwargs):
        super().__init__(*args, **kwargs)


class SocieteDocumentForm(forms.ModelForm):
    """Document de la société (fichier téléversé)."""

    fichier = forms.FileField(label="Fichier (PDF)")

    class Meta:
        model = SocieteDocument
        fields = [
            "type_document",
            "numero_document",
            "fichier",
            "date_emission",
            "date_expiration",
        ]
        widgets = {
            "date_emission": forms.DateInput(attrs={"type": "date"}),
            "date_expiration": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, societe=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["numero_document"].required = False
        self.fields["date_emission"].required = False
        self.fields["date_expiration"].required = False
        # En modification, garder le fichier existant si aucun nouveau n'est choisi
        if self.instance.pk:
            self.fields["fichier"].required = False