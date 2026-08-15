/**
 * Translations for the studio.
 *
 * Three locales, two writing directions. Arabic is the reason this is a
 * real feature rather than a string swap: the whole layout mirrors, dates
 * and numbers come from Intl rather than hand-built strings, and plurals
 * follow each language's own rules (Arabic has six categories, French
 * treats zero as singular, English does not).
 */

export const LOCALES = {
  en: { label: 'English', dir: 'ltr', intl: 'en-GB' },
  fr: { label: 'Français', dir: 'ltr', intl: 'fr-FR' },
  ar: { label: 'العربية', dir: 'rtl', intl: 'ar' },
};

const CATALOG = {
  en: {
    'app.name': 'Night Shift',
    'app.tagline': 'Rota Studio',
    'app.signIn': 'Sign in',
    'app.settings': 'Settings',
    'app.theme': 'Toggle theme',
    'app.language': 'Language',
    'api.checking': 'checking API…',
    'api.online': 'API online',
    'api.offline': 'API unreachable',

    'step.period': 'Period',
    'step.roster': 'Roster',
    'step.coverage': 'Coverage',
    'step.rules': 'Calendar rules',
    'step.availability': 'Availability',
    'step.effort': 'Search effort',

    'period.start': 'Start',
    'period.end': 'End',
    'period.thisMonth': 'This month',
    'period.nextMonth': 'Next month',
    'period.fourWeeks': 'Next 4 weeks',
    'period.invalid': 'invalid range',
    'period.summary': '{nights} · {weekends} weekend',

    'roster.add': 'Add a doctor, or paste a comma-separated list…',
    'roster.demo': 'Load a demo department',
    'roster.clear': 'Clear roster',
    'roster.empty': 'No doctors yet — add them one by one, or paste a comma-separated list.',
    'roster.graded': 'Department is graded',
    'roster.gradedHint': 'Seniority tiers are staffed independently each night',
    'roster.addGrade': 'Add a grade (e.g. Consultant)',
    'roster.gradeHint': 'Assign each doctor a grade using the selectors above.',
    'roster.remove': 'Remove {name}',
    'roster.off': '{count} off',
    'roster.added': '{count} added',

    'coverage.same': 'Same every night',
    'coverage.custom': 'Per-night',
    'coverage.perNight': 'Doctors on call per night',
    'coverage.gradedNote': 'Applied <b>per grade</b> — with {grades} grades that is <b>{total} doctors</b> on call each night.',
    'coverage.customHint': 'Set the required headcount for each night. Weekends and holidays are highlighted.',
    'coverage.all1': 'All 1',
    'coverage.all2': 'All 2',
    'coverage.weekendPlus': 'Weekends +1',
    'coverage.total': '{shifts} total',

    'rules.weekday': 'weekday',
    'rules.saturday': 'Saturday',
    'rules.sunday': 'Sunday',
    'rules.holiday': 'holiday',
    'rules.hint': 'Click any night to flag it as a public holiday — it then carries the heaviest weight when balancing.',
    'rules.holidays': '{count} holidays',

    'avail.doctor': 'Doctor',
    'avail.hint': 'Click nights this doctor cannot cover — leave, conference, post-nights.',
    'avail.none': 'no blackouts',
    'avail.blocked': '{nights} blocked',
    'avail.clear': 'clear',
    'avail.addFirst': '— add doctors first —',

    'effort.draft': 'Draft',
    'effort.quick': 'Quick',
    'effort.balanced': 'Balanced',
    'effort.thorough': 'Thorough',
    'effort.exhaustive': 'Exhaustive',
    'effort.hint': '<b>{count}</b> candidate rotas. {blurb}',
    'effort.blurb.draft': 'A single quick pass — good for sanity-checking the setup.',
    'effort.blurb.quick': 'Fast turnaround, usually a decent rota.',
    'effort.blurb.balanced': 'The sweet spot for most departments.',
    'effort.blurb.thorough': 'Searches hard for an even points split. Takes longer.',
    'effort.blurb.exhaustive': 'Best fairness the engine can find. Expect a wait.',

    'generate': 'Generate rota',
    'regenerate': 'Regenerate',
    'retune': 'Re-tune',
    'retuneHint': 'Re-solve the nights you have not pinned, moving as little as possible',
    'print': 'Print',

    'tab.calendar': 'Calendar',
    'tab.fairness': 'Fairness',
    'tab.insights': 'Insights',
    'tab.export': 'Export',
    'tab.history': 'History',

    'empty.title': 'Balance the nights, not the spreadsheet.',
    'empty.body': 'Build your roster on the left and the studio will model the department’s own rest rule, check every night for feasibility before a single request is sent, then hunt for the fairest rota it can find — and audit the one it gets back.',
    'empty.cta': 'Try a demo department',
    'empty.weights': '<b>Weights</b> Sat 1.5 · Sun &amp; holidays 2.0 · weekdays 1.0',
    'empty.rest': '<b>Rest</b> a night off between shifts, and never more than 2 in any 7',
    'empty.audit': '<b>Audit</b> every returned rota is re-checked against your constraints',

    'stat.balance': 'Balance',
    'stat.balanceSub': 'evenness of the points split',
    'stat.coverage': 'Coverage',
    'stat.coverageSub': '{assigned} of {required} shifts filled',
    'stat.pointsSpread': 'Points spread',
    'stat.pointsSpreadSub': 'heaviest minus lightest',
    'stat.weekendSpread': 'Weekend spread',
    'stat.weekendSpreadSub': 'weekend shifts, max − min',
    'stat.score': 'Engine score',
    'stat.scoreSub': 'lower is fairer',

    'legend.holiday': 'Holiday · 2.0',
    'legend.weekend': 'Weekend · 1.5 / 2.0',
    'legend.short': 'Understaffed night',
    'legend.b2b': 'Back-to-back night',
    'cal.months': '{nights} · {shifts}',
    'cal.unfilled': 'unfilled',
    'cal.shortBy': 'short {count}',
    'cal.nobody': '— nobody on call —',

    'fair.points': 'Points balance',
    'fair.pointsSub': 'Weekdays 1.0 · Saturdays 1.5 · Sundays and holidays 2.0',
    'fair.load': 'Load per doctor',
    'fair.loadSub': 'Total points earned across the period',
    'fair.weekend': 'Weekend & holiday duty',
    'fair.weekendSub': 'The nights people actually count',
    'fair.rhythm': 'Rhythm',
    'fair.rhythmSub': 'One block per night. Filled = on call, dimmed = weekend, amber = holiday, hatched = booked leave, ringed = back-to-back.',
    'fair.table': 'Doctor by doctor',
    'fair.tableSub': 'Gap = nights between consecutive shifts',
    'fair.average': 'Average load',
    'fair.heaviest': 'Heaviest',
    'fair.lightest': 'Lightest',
    'fair.spread': 'Spread',
    'fair.points.word': 'points',
    'fair.balanceLabel': 'balance',
    'th.doctor': 'Doctor',
    'th.grade': 'Grade',
    'th.shifts': 'Shifts',
    'th.weekend': 'Weekend',
    'th.holiday': 'Holiday',
    'th.pointsCol': 'Points',
    'th.minGap': 'Min gap',
    'th.avgGap': 'Avg gap',
    'th.flags': 'Flags',
    'flag.clean': 'clean',
    'flag.leaveClash': '{count} leave clash',
    'flag.b2b': '{count} back-to-back',

    'export.csv': 'Rota as CSV',
    'export.csvSub': 'One row per night with everyone on call — opens in Excel or Sheets.',
    'export.workload': 'Workload as CSV',
    'export.workloadSub': 'Per-doctor totals: shifts, weekends, holidays, points and gaps.',
    'export.ics': 'Calendar file (.ics)',
    'export.icsSub': '{count} all-day events — import into Outlook, Google or Apple Calendar.',
    'export.print': 'Print / PDF',
    'export.printSub': 'A clean ward-noticeboard layout, no controls.',
    'export.json': 'Copy JSON',
    'export.jsonSub': 'The raw API response, for pasting elsewhere.',
    'export.payload': 'Copy request payload',
    'export.payloadSub': 'Reproduce this exact run against the API.',
    'export.pdfDiary': 'PDF · diary',
    'export.pdfDiarySub': 'One row per night, A4 portrait. Rendered on the server.',
    'export.pdfWall': 'PDF · wall chart',
    'export.pdfWallSub': 'Doctors as columns, A4 landscape.',
    'export.pdfBoard': 'PDF · noticeboard',
    'export.pdfBoardSub': 'Month grid, A4 landscape.',
    'export.share': 'Create a share link',
    'export.shareSub': 'A read-only page anyone can open without an account.',
    'export.response': 'API response',

    'share.title': 'Share links',
    'share.sub': 'Read-only pages that need no account. Only a hash of each token is stored, so a link can be revoked but never recovered.',
    'share.none': 'No links yet.',
    'share.revoke': 'Revoke',
    'share.revoked': 'revoked',
    'share.copy': 'Copy',
    'share.copied': 'Share link copied',
    'share.copiedSub': 'Read-only, no account needed.',
    'share.views': '{count} views',

    'history.saved': 'Saved rotas',
    'history.savedSub': '{count} in {department}',
    'history.emptyServer': 'Nothing saved yet. Generate a rota and it is kept here for your whole department.',
    'history.local': 'Run history',
    'history.localSub': '{count} kept on this device',
    'history.emptyLocal': 'No runs yet. Generated rotas are kept here so you can compare and restore them.',
    'history.open': 'Open',
    'history.clear': 'Clear history',
    'history.delete': 'Delete',

    'menu.on': '{name} · {date}',
    'menu.takeOff': 'Take off this night',
    'menu.pin': 'Pin to this night',
    'menu.unpin': 'Unpin (allow re-solving)',
    'menu.swapWith': 'Swap with',
    'menu.allOn': 'Everyone else is already on call.',
    'menu.onLeave': 'on leave',
    'menu.pinned': 'Pinned — a re-solve leaves this alone',

    'auth.signIn': 'Sign in',
    'auth.signUp': 'Create an account',
    'auth.blurb': 'Signing in saves your roster and rotas, and unlocks editing, PDF export and share links.',
    'auth.name': 'Your name',
    'auth.email': 'Email',
    'auth.password': 'Password',
    'auth.department': 'Department name',
    'auth.departmentPlaceholder': 'e.g. Emergency Medicine',
    'auth.cancel': 'Cancel',
    'auth.create': 'Create account',
    'auth.noAccount': 'No account yet?',
    'auth.haveAccount': 'Already have an account?',
    'auth.createOne': 'Create one',
    'auth.signedIn': 'Signed in as {name}',
    'auth.carried': 'Your {count} moved across.',
    'auth.signedOut': 'Signed out',
    'auth.signedOutSub': 'The studio keeps working without an account.',
    'auth.signOutTitle': '{email} — click to sign out',

    'settings.title': 'Settings',
    'settings.apiBase': 'API base URL',
    'settings.apiHint': 'Leave blank when the studio is served by the FastAPI app itself.',
    'settings.remember': 'Remember my roster and rules on this device',
    'settings.close': 'Close',
    'settings.save': 'Save',
    'settings.saved': 'Settings saved',

    'run.title': 'Searching for a fair rota…',
    'run.elapsed': 'elapsed',
    'run.stage1': 'Sampling candidate rotas',
    'run.stage2': 'Applying the rest rule',
    'run.stage3': 'Scoring points balance',
    'run.stage4': 'Comparing weekend fairness',
    'run.stage5': 'Picking the most even rota',
    'run.saving': 'Saving roster and solving',

    'toast.generated': 'Rota generated',
    'toast.generatedSub': '{shifts} placed in {seconds}s · balance {balance}%',
    'toast.saved': 'Rota saved',
    'toast.failed': 'Could not generate a rota',
    'toast.editRefused': 'Edit refused',
    'toast.retuned': 'Re-tuned around your pinned nights',
    'toast.demo': 'Demo department loaded',
    'toast.demoSub': '10 doctors, 2 on call each night, two blocks of leave and one public holiday.',
    'toast.restored': 'Rota restored',
    'toast.downloaded': 'Downloaded',
    'toast.copied': 'Copied to clipboard',
    'toast.clipboardBlocked': 'Clipboard blocked',

    'valid.ok': 'This rota is valid',
    'valid.okSub': 'Coverage, leave and rest all check out against the department rules.',
    'valid.warnNote': 'Warnings do not block publishing.',

    'unit.night': '{count} nights',
    'unit.doctor': '{count} doctors',
    'unit.shift': '{count} shifts',
    'unit.rota': '{count} rotas',
  },

  fr: {
    'app.name': 'Night Shift',
    'app.tagline': 'Studio de garde',
    'app.signIn': 'Se connecter',
    'app.settings': 'Paramètres',
    'app.theme': 'Changer de thème',
    'app.language': 'Langue',
    'api.checking': 'vérification de l’API…',
    'api.online': 'API en ligne',
    'api.offline': 'API injoignable',

    'step.period': 'Période',
    'step.roster': 'Effectif',
    'step.coverage': 'Couverture',
    'step.rules': 'Règles du calendrier',
    'step.availability': 'Disponibilités',
    'step.effort': 'Effort de recherche',

    'period.start': 'Début',
    'period.end': 'Fin',
    'period.thisMonth': 'Ce mois-ci',
    'period.nextMonth': 'Le mois prochain',
    'period.fourWeeks': '4 prochaines semaines',
    'period.invalid': 'période invalide',
    'period.summary': '{nights} · {weekends} week-end',

    'roster.add': 'Ajouter un médecin, ou coller une liste séparée par des virgules…',
    'roster.demo': 'Charger un service de démonstration',
    'roster.clear': 'Vider l’effectif',
    'roster.empty': 'Aucun médecin — ajoutez-les un par un, ou collez une liste séparée par des virgules.',
    'roster.graded': 'Service à grades',
    'roster.gradedHint': 'Chaque grade est couvert indépendamment chaque nuit',
    'roster.addGrade': 'Ajouter un grade (ex. Praticien)',
    'roster.gradeHint': 'Attribuez un grade à chaque médecin avec les sélecteurs ci-dessus.',
    'roster.remove': 'Retirer {name}',
    'roster.off': '{count} absences',
    'roster.added': '{count} ajoutés',

    'coverage.same': 'Identique chaque nuit',
    'coverage.custom': 'Par nuit',
    'coverage.perNight': 'Médecins de garde par nuit',
    'coverage.gradedNote': 'Appliqué <b>par grade</b> — avec {grades} grades cela fait <b>{total} médecins</b> de garde chaque nuit.',
    'coverage.customHint': 'Définissez l’effectif requis pour chaque nuit. Week-ends et jours fériés sont mis en évidence.',
    'coverage.all1': 'Tous à 1',
    'coverage.all2': 'Tous à 2',
    'coverage.weekendPlus': 'Week-ends +1',
    'coverage.total': '{shifts} au total',

    'rules.weekday': 'jour ouvré',
    'rules.saturday': 'samedi',
    'rules.sunday': 'dimanche',
    'rules.holiday': 'jour férié',
    'rules.hint': 'Cliquez une nuit pour la marquer comme jour férié — elle prend alors le poids le plus lourd dans l’équilibrage.',
    'rules.holidays': '{count} jours fériés',

    'avail.doctor': 'Médecin',
    'avail.hint': 'Cliquez les nuits que ce médecin ne peut pas couvrir — congés, congrès, repos de garde.',
    'avail.none': 'aucune indisponibilité',
    'avail.blocked': '{nights} bloquées',
    'avail.clear': 'effacer',
    'avail.addFirst': '— ajoutez d’abord des médecins —',

    'effort.draft': 'Brouillon',
    'effort.quick': 'Rapide',
    'effort.balanced': 'Équilibré',
    'effort.thorough': 'Approfondi',
    'effort.exhaustive': 'Exhaustif',
    'effort.hint': '<b>{count}</b> plannings candidats. {blurb}',
    'effort.blurb.draft': 'Une passe rapide — utile pour vérifier la configuration.',
    'effort.blurb.quick': 'Résultat rapide, généralement correct.',
    'effort.blurb.balanced': 'Le bon compromis pour la plupart des services.',
    'effort.blurb.thorough': 'Cherche longuement une répartition égale des points.',
    'effort.blurb.exhaustive': 'La meilleure équité possible. Prévoyez d’attendre.',

    'generate': 'Générer le planning',
    'regenerate': 'Régénérer',
    'retune': 'Réajuster',
    'retuneHint': 'Recalcule les nuits non épinglées en bougeant le moins possible',
    'print': 'Imprimer',

    'tab.calendar': 'Calendrier',
    'tab.fairness': 'Équité',
    'tab.insights': 'Analyse',
    'tab.export': 'Export',
    'tab.history': 'Historique',

    'empty.title': 'Équilibrez les gardes, pas le tableur.',
    'empty.body': 'Constituez votre effectif à gauche : le studio applique la règle de repos du service, vérifie la faisabilité de chaque nuit avant même d’envoyer une requête, cherche le planning le plus équitable possible — puis audite celui qu’il obtient.',
    'empty.cta': 'Essayer un service de démonstration',
    'empty.weights': '<b>Poids</b> sam. 1,5 · dim. et fériés 2,0 · jours ouvrés 1,0',
    'empty.rest': '<b>Repos</b> une nuit entre deux gardes, et jamais plus de 2 sur 7',
    'empty.audit': '<b>Audit</b> chaque planning est revérifié contre vos contraintes',

    'stat.balance': 'Équilibre',
    'stat.balanceSub': 'régularité de la répartition des points',
    'stat.coverage': 'Couverture',
    'stat.coverageSub': '{assigned} gardes sur {required} pourvues',
    'stat.pointsSpread': 'Écart de points',
    'stat.pointsSpreadSub': 'le plus chargé moins le moins chargé',
    'stat.weekendSpread': 'Écart week-end',
    'stat.weekendSpreadSub': 'gardes de week-end, max − min',
    'stat.score': 'Score du moteur',
    'stat.scoreSub': 'plus bas = plus équitable',

    'legend.holiday': 'Jour férié · 2,0',
    'legend.weekend': 'Week-end · 1,5 / 2,0',
    'legend.short': 'Nuit en sous-effectif',
    'legend.b2b': 'Gardes consécutives',
    'cal.months': '{nights} · {shifts}',
    'cal.unfilled': 'non pourvue',
    'cal.shortBy': 'manque {count}',
    'cal.nobody': '— personne de garde —',

    'fair.points': 'Équilibre des points',
    'fair.pointsSub': 'Jours ouvrés 1,0 · samedis 1,5 · dimanches et fériés 2,0',
    'fair.load': 'Charge par médecin',
    'fair.loadSub': 'Total des points sur la période',
    'fair.weekend': 'Week-ends et jours fériés',
    'fair.weekendSub': 'Les nuits qui comptent vraiment',
    'fair.rhythm': 'Rythme',
    'fair.rhythmSub': 'Un bloc par nuit. Plein = de garde, atténué = week-end, ambre = férié, hachuré = congé, cerclé = gardes consécutives.',
    'fair.table': 'Médecin par médecin',
    'fair.tableSub': 'Écart = nuits entre deux gardes consécutives',
    'fair.average': 'Charge moyenne',
    'fair.heaviest': 'Le plus chargé',
    'fair.lightest': 'Le moins chargé',
    'fair.spread': 'Écart',
    'fair.points.word': 'points',
    'fair.balanceLabel': 'équilibre',
    'th.doctor': 'Médecin',
    'th.grade': 'Grade',
    'th.shifts': 'Gardes',
    'th.weekend': 'Week-end',
    'th.holiday': 'Férié',
    'th.pointsCol': 'Points',
    'th.minGap': 'Écart min',
    'th.avgGap': 'Écart moy',
    'th.flags': 'Signalements',
    'flag.clean': 'conforme',
    'flag.leaveClash': '{count} conflit de congé',
    'flag.b2b': '{count} consécutives',

    'export.csv': 'Planning en CSV',
    'export.csvSub': 'Une ligne par nuit avec les médecins de garde — s’ouvre dans Excel.',
    'export.workload': 'Charge en CSV',
    'export.workloadSub': 'Totaux par médecin : gardes, week-ends, fériés, points et écarts.',
    'export.ics': 'Fichier calendrier (.ics)',
    'export.icsSub': '{count} événements — à importer dans Outlook, Google ou Apple Calendar.',
    'export.print': 'Imprimer / PDF',
    'export.printSub': 'Une mise en page sobre pour le tableau de service.',
    'export.json': 'Copier le JSON',
    'export.jsonSub': 'La réponse brute de l’API.',
    'export.payload': 'Copier la requête',
    'export.payloadSub': 'Reproduire exactement cet appel contre l’API.',
    'export.pdfDiary': 'PDF · agenda',
    'export.pdfDiarySub': 'Une ligne par nuit, A4 portrait. Rendu côté serveur.',
    'export.pdfWall': 'PDF · tableau mural',
    'export.pdfWallSub': 'Médecins en colonnes, A4 paysage.',
    'export.pdfBoard': 'PDF · tableau de service',
    'export.pdfBoardSub': 'Grille mensuelle, A4 paysage.',
    'export.share': 'Créer un lien de partage',
    'export.shareSub': 'Une page en lecture seule, sans compte.',
    'export.response': 'Réponse de l’API',

    'share.title': 'Liens de partage',
    'share.sub': 'Pages en lecture seule, sans compte. Seule une empreinte du jeton est stockée : un lien peut être révoqué mais jamais retrouvé.',
    'share.none': 'Aucun lien pour l’instant.',
    'share.revoke': 'Révoquer',
    'share.revoked': 'révoqué',
    'share.copy': 'Copier',
    'share.copied': 'Lien copié',
    'share.copiedSub': 'Lecture seule, sans compte.',
    'share.views': '{count} vues',

    'history.saved': 'Plannings enregistrés',
    'history.savedSub': '{count} dans {department}',
    'history.emptyServer': 'Rien d’enregistré. Générez un planning : il sera conservé pour tout le service.',
    'history.local': 'Historique',
    'history.localSub': '{count} conservés sur cet appareil',
    'history.emptyLocal': 'Aucun essai. Les plannings générés sont conservés ici pour comparaison.',
    'history.open': 'Ouvrir',
    'history.clear': 'Vider l’historique',
    'history.delete': 'Supprimer',

    'menu.on': '{name} · {date}',
    'menu.takeOff': 'Retirer de cette nuit',
    'menu.pin': 'Épingler à cette nuit',
    'menu.unpin': 'Désépingler (autoriser le recalcul)',
    'menu.swapWith': 'Échanger avec',
    'menu.allOn': 'Tous les autres sont déjà de garde.',
    'menu.onLeave': 'en congé',
    'menu.pinned': 'Épinglé — un recalcul n’y touchera pas',

    'auth.signIn': 'Se connecter',
    'auth.signUp': 'Créer un compte',
    'auth.blurb': 'La connexion enregistre votre effectif et vos plannings, et débloque l’édition, l’export PDF et les liens de partage.',
    'auth.name': 'Votre nom',
    'auth.email': 'E-mail',
    'auth.password': 'Mot de passe',
    'auth.department': 'Nom du service',
    'auth.departmentPlaceholder': 'ex. Urgences',
    'auth.cancel': 'Annuler',
    'auth.create': 'Créer le compte',
    'auth.noAccount': 'Pas encore de compte ?',
    'auth.haveAccount': 'Vous avez déjà un compte ?',
    'auth.createOne': 'En créer un',
    'auth.signedIn': 'Connecté en tant que {name}',
    'auth.carried': 'Vos {count} ont été repris.',
    'auth.signedOut': 'Déconnecté',
    'auth.signedOutSub': 'Le studio fonctionne toujours sans compte.',
    'auth.signOutTitle': '{email} — cliquer pour se déconnecter',

    'settings.title': 'Paramètres',
    'settings.apiBase': 'URL de base de l’API',
    'settings.apiHint': 'Laissez vide si le studio est servi par l’application FastAPI elle-même.',
    'settings.remember': 'Mémoriser mon effectif et mes règles sur cet appareil',
    'settings.close': 'Fermer',
    'settings.save': 'Enregistrer',
    'settings.saved': 'Paramètres enregistrés',

    'run.title': 'Recherche d’un planning équitable…',
    'run.elapsed': 'écoulées',
    'run.stage1': 'Échantillonnage des plannings',
    'run.stage2': 'Application de la règle de repos',
    'run.stage3': 'Évaluation de l’équilibre des points',
    'run.stage4': 'Comparaison de l’équité des week-ends',
    'run.stage5': 'Sélection du planning le plus régulier',
    'run.saving': 'Enregistrement de l’effectif et résolution',

    'toast.generated': 'Planning généré',
    'toast.generatedSub': '{shifts} placées en {seconds}s · équilibre {balance}%',
    'toast.saved': 'Planning enregistré',
    'toast.failed': 'Impossible de générer un planning',
    'toast.editRefused': 'Modification refusée',
    'toast.retuned': 'Réajusté autour de vos nuits épinglées',
    'toast.demo': 'Service de démonstration chargé',
    'toast.demoSub': '10 médecins, 2 de garde par nuit, deux périodes de congé et un jour férié.',
    'toast.restored': 'Planning restauré',
    'toast.downloaded': 'Téléchargé',
    'toast.copied': 'Copié dans le presse-papiers',
    'toast.clipboardBlocked': 'Presse-papiers bloqué',

    'valid.ok': 'Ce planning est valide',
    'valid.okSub': 'Couverture, congés et repos respectent les règles du service.',
    'valid.warnNote': 'Les avertissements ne bloquent pas la publication.',

    'unit.night': '{count} nuits',
    'unit.doctor': '{count} médecins',
    'unit.shift': '{count} gardes',
    'unit.rota': '{count} plannings',
  },

  ar: {
    'app.name': 'مناوبة الليل',
    'app.tagline': 'استوديو الجداول',
    'app.signIn': 'تسجيل الدخول',
    'app.settings': 'الإعدادات',
    'app.theme': 'تبديل المظهر',
    'app.language': 'اللغة',
    'api.checking': 'جارٍ التحقق من الواجهة…',
    'api.online': 'الواجهة متصلة',
    'api.offline': 'الواجهة غير متاحة',

    'step.period': 'الفترة',
    'step.roster': 'الفريق',
    'step.coverage': 'التغطية',
    'step.rules': 'قواعد التقويم',
    'step.availability': 'التوفر',
    'step.effort': 'جهد البحث',

    'period.start': 'من',
    'period.end': 'إلى',
    'period.thisMonth': 'هذا الشهر',
    'period.nextMonth': 'الشهر القادم',
    'period.fourWeeks': 'الأسابيع الأربعة القادمة',
    'period.invalid': 'فترة غير صالحة',
    'period.summary': '{nights} · {weekends} عطلة نهاية أسبوع',

    'roster.add': 'أضف طبيبًا، أو الصق قائمة مفصولة بفواصل…',
    'roster.demo': 'تحميل قسم تجريبي',
    'roster.clear': 'مسح الفريق',
    'roster.empty': 'لا يوجد أطباء بعد — أضفهم واحدًا تلو الآخر، أو الصق قائمة مفصولة بفواصل.',
    'roster.graded': 'القسم مقسّم إلى درجات',
    'roster.gradedHint': 'كل درجة تُغطّى بشكل مستقل في كل ليلة',
    'roster.addGrade': 'أضف درجة (مثل: استشاري)',
    'roster.gradeHint': 'حدّد درجة كل طبيب من القوائم أعلاه.',
    'roster.remove': 'إزالة {name}',
    'roster.off': '{count} إجازة',
    'roster.added': 'تمت إضافة {count}',

    'coverage.same': 'نفس العدد كل ليلة',
    'coverage.custom': 'لكل ليلة',
    'coverage.perNight': 'عدد الأطباء المناوبين كل ليلة',
    'coverage.gradedNote': 'يُطبَّق <b>لكل درجة</b> — مع {grades} درجات يصبح <b>{total} طبيبًا</b> في كل ليلة.',
    'coverage.customHint': 'حدّد العدد المطلوب لكل ليلة. عطل نهاية الأسبوع والأعياد مميّزة.',
    'coverage.all1': 'الكل 1',
    'coverage.all2': 'الكل 2',
    'coverage.weekendPlus': 'عطلة الأسبوع +1',
    'coverage.total': '{shifts} إجمالًا',

    'rules.weekday': 'يوم عمل',
    'rules.saturday': 'السبت',
    'rules.sunday': 'الأحد',
    'rules.holiday': 'عطلة رسمية',
    'rules.hint': 'انقر أي ليلة لتعيينها عطلة رسمية — عندها تحمل أثقل وزن في الموازنة.',
    'rules.holidays': '{count} عطل رسمية',

    'avail.doctor': 'الطبيب',
    'avail.hint': 'انقر الليالي التي لا يستطيع هذا الطبيب تغطيتها — إجازة، مؤتمر، راحة بعد المناوبة.',
    'avail.none': 'لا توجد فترات حجب',
    'avail.blocked': '{nights} محجوبة',
    'avail.clear': 'مسح',
    'avail.addFirst': '— أضف أطباء أولًا —',

    'effort.draft': 'مسودة',
    'effort.quick': 'سريع',
    'effort.balanced': 'متوازن',
    'effort.thorough': 'دقيق',
    'effort.exhaustive': 'شامل',
    'effort.hint': '<b>{count}</b> جدولًا مرشحًا. {blurb}',
    'effort.blurb.draft': 'محاولة سريعة واحدة — مفيدة للتحقق من الإعداد.',
    'effort.blurb.quick': 'نتيجة سريعة، وجدول مقبول عادة.',
    'effort.blurb.balanced': 'الخيار الأنسب لمعظم الأقسام.',
    'effort.blurb.thorough': 'يبحث بعمق عن توزيع متساوٍ للنقاط. يستغرق وقتًا أطول.',
    'effort.blurb.exhaustive': 'أفضل عدالة يمكن للمحرك بلوغها. توقّع الانتظار.',

    'generate': 'إنشاء الجدول',
    'regenerate': 'إعادة الإنشاء',
    'retune': 'إعادة الضبط',
    'retuneHint': 'يعيد حل الليالي غير المثبّتة مع أقل تغيير ممكن',
    'print': 'طباعة',

    'tab.calendar': 'التقويم',
    'tab.fairness': 'العدالة',
    'tab.insights': 'التحليل',
    'tab.export': 'التصدير',
    'tab.history': 'السجل',

    'empty.title': 'وازِن الليالي، لا الجداول.',
    'empty.body': 'كوّن فريقك على الجانب، وسيطبّق الاستوديو قاعدة الراحة الخاصة بالقسم، ويتحقق من إمكانية تغطية كل ليلة قبل إرسال أي طلب، ثم يبحث عن أعدل جدول ممكن — ويدقّق الجدول الذي يحصل عليه.',
    'empty.cta': 'جرّب قسمًا تجريبيًا',
    'empty.weights': '<b>الأوزان</b> السبت 1.5 · الأحد والأعياد 2.0 · أيام العمل 1.0',
    'empty.rest': '<b>الراحة</b> ليلة راحة بين المناوبات، ولا أكثر من 2 في كل 7',
    'empty.audit': '<b>التدقيق</b> كل جدول يُعاد فحصه مقابل قيودك',

    'stat.balance': 'التوازن',
    'stat.balanceSub': 'انتظام توزيع النقاط',
    'stat.coverage': 'التغطية',
    'stat.coverageSub': 'تمت تغطية {assigned} من {required}',
    'stat.pointsSpread': 'فارق النقاط',
    'stat.pointsSpreadSub': 'الأثقل ناقص الأخف',
    'stat.weekendSpread': 'فارق عطلة الأسبوع',
    'stat.weekendSpreadSub': 'مناوبات العطلة، الأعلى − الأدنى',
    'stat.score': 'نتيجة المحرك',
    'stat.scoreSub': 'الأقل أعدل',

    'legend.holiday': 'عطلة رسمية · 2.0',
    'legend.weekend': 'عطلة الأسبوع · 1.5 / 2.0',
    'legend.short': 'ليلة ناقصة التغطية',
    'legend.b2b': 'مناوبات متتالية',
    'cal.months': '{nights} · {shifts}',
    'cal.unfilled': 'غير مغطاة',
    'cal.shortBy': 'ينقص {count}',
    'cal.nobody': '— لا أحد مناوب —',

    'fair.points': 'توازن النقاط',
    'fair.pointsSub': 'أيام العمل 1.0 · السبت 1.5 · الأحد والأعياد 2.0',
    'fair.load': 'العبء لكل طبيب',
    'fair.loadSub': 'مجموع النقاط خلال الفترة',
    'fair.weekend': 'مناوبات العطل والأعياد',
    'fair.weekendSub': 'الليالي التي تُحتسب فعلًا',
    'fair.rhythm': 'الإيقاع',
    'fair.rhythmSub': 'مربع لكل ليلة. ممتلئ = مناوب، باهت = عطلة أسبوع، كهرماني = عيد، مخطط = إجازة، محاط = مناوبتان متتاليتان.',
    'fair.table': 'طبيبًا بطبيب',
    'fair.tableSub': 'الفارق = الليالي بين مناوبتين متتاليتين',
    'fair.average': 'متوسط العبء',
    'fair.heaviest': 'الأثقل',
    'fair.lightest': 'الأخف',
    'fair.spread': 'الفارق',
    'fair.points.word': 'نقطة',
    'fair.balanceLabel': 'التوازن',
    'th.doctor': 'الطبيب',
    'th.grade': 'الدرجة',
    'th.shifts': 'المناوبات',
    'th.weekend': 'العطلة',
    'th.holiday': 'العيد',
    'th.pointsCol': 'النقاط',
    'th.minGap': 'أدنى فارق',
    'th.avgGap': 'متوسط الفارق',
    'th.flags': 'الملاحظات',
    'flag.clean': 'سليم',
    'flag.leaveClash': '{count} تعارض إجازة',
    'flag.b2b': '{count} متتالية',

    'export.csv': 'الجدول بصيغة CSV',
    'export.csvSub': 'سطر لكل ليلة مع المناوبين — يُفتح في Excel.',
    'export.workload': 'العبء بصيغة CSV',
    'export.workloadSub': 'إجماليات كل طبيب: المناوبات والعطل والأعياد والنقاط.',
    'export.ics': 'ملف تقويم (.ics)',
    'export.icsSub': '{count} حدثًا — للاستيراد إلى Outlook أو Google أو Apple.',
    'export.print': 'طباعة / PDF',
    'export.printSub': 'تخطيط نظيف للوحة القسم، بلا أدوات.',
    'export.json': 'نسخ JSON',
    'export.jsonSub': 'استجابة الواجهة الخام.',
    'export.payload': 'نسخ الطلب',
    'export.payloadSub': 'إعادة تنفيذ هذا الطلب نفسه على الواجهة.',
    'export.pdfDiary': 'PDF · يومية',
    'export.pdfDiarySub': 'سطر لكل ليلة، A4 عمودي. يُنشأ على الخادم.',
    'export.pdfWall': 'PDF · لوحة جدارية',
    'export.pdfWallSub': 'الأطباء كأعمدة، A4 أفقي.',
    'export.pdfBoard': 'PDF · لوحة القسم',
    'export.pdfBoardSub': 'شبكة شهرية، A4 أفقي.',
    'export.share': 'إنشاء رابط مشاركة',
    'export.shareSub': 'صفحة للقراءة فقط تُفتح بلا حساب.',
    'export.response': 'استجابة الواجهة',

    'share.title': 'روابط المشاركة',
    'share.sub': 'صفحات للقراءة فقط بلا حساب. تُخزَّن بصمة الرمز فقط، لذا يمكن إبطال الرابط لا استرجاعه.',
    'share.none': 'لا توجد روابط بعد.',
    'share.revoke': 'إبطال',
    'share.revoked': 'مُبطَل',
    'share.copy': 'نسخ',
    'share.copied': 'تم نسخ الرابط',
    'share.copiedSub': 'للقراءة فقط، بلا حساب.',
    'share.views': '{count} مشاهدة',

    'history.saved': 'الجداول المحفوظة',
    'history.savedSub': '{count} في {department}',
    'history.emptyServer': 'لا شيء محفوظ بعد. أنشئ جدولًا وسيُحفظ هنا للقسم بأكمله.',
    'history.local': 'سجل المحاولات',
    'history.localSub': '{count} محفوظة على هذا الجهاز',
    'history.emptyLocal': 'لا توجد محاولات. تُحفظ الجداول هنا للمقارنة والاسترجاع.',
    'history.open': 'فتح',
    'history.clear': 'مسح السجل',
    'history.delete': 'حذف',

    'menu.on': '{name} · {date}',
    'menu.takeOff': 'إزالة من هذه الليلة',
    'menu.pin': 'تثبيت في هذه الليلة',
    'menu.unpin': 'إلغاء التثبيت (السماح بإعادة الحل)',
    'menu.swapWith': 'تبديل مع',
    'menu.allOn': 'الجميع مناوبون بالفعل.',
    'menu.onLeave': 'في إجازة',
    'menu.pinned': 'مثبّت — إعادة الحل لن تغيّره',

    'auth.signIn': 'تسجيل الدخول',
    'auth.signUp': 'إنشاء حساب',
    'auth.blurb': 'تسجيل الدخول يحفظ فريقك وجداولك، ويتيح التحرير وتصدير PDF وروابط المشاركة.',
    'auth.name': 'اسمك',
    'auth.email': 'البريد الإلكتروني',
    'auth.password': 'كلمة المرور',
    'auth.department': 'اسم القسم',
    'auth.departmentPlaceholder': 'مثل: الطوارئ',
    'auth.cancel': 'إلغاء',
    'auth.create': 'إنشاء الحساب',
    'auth.noAccount': 'ليس لديك حساب؟',
    'auth.haveAccount': 'لديك حساب بالفعل؟',
    'auth.createOne': 'أنشئ واحدًا',
    'auth.signedIn': 'تم تسجيل الدخول باسم {name}',
    'auth.carried': 'تم نقل {count}.',
    'auth.signedOut': 'تم تسجيل الخروج',
    'auth.signedOutSub': 'الاستوديو يعمل بلا حساب أيضًا.',
    'auth.signOutTitle': '{email} — انقر لتسجيل الخروج',

    'settings.title': 'الإعدادات',
    'settings.apiBase': 'عنوان الواجهة',
    'settings.apiHint': 'اتركه فارغًا إذا كان الاستوديو يُقدَّم من تطبيق FastAPI نفسه.',
    'settings.remember': 'تذكّر فريقي وقواعدي على هذا الجهاز',
    'settings.close': 'إغلاق',
    'settings.save': 'حفظ',
    'settings.saved': 'تم حفظ الإعدادات',

    'run.title': 'جارٍ البحث عن جدول عادل…',
    'run.elapsed': 'منقضية',
    'run.stage1': 'أخذ عيّنات من الجداول',
    'run.stage2': 'تطبيق قاعدة الراحة',
    'run.stage3': 'تقييم توازن النقاط',
    'run.stage4': 'مقارنة عدالة العطل',
    'run.stage5': 'اختيار الجدول الأكثر انتظامًا',
    'run.saving': 'حفظ الفريق وحل الجدول',

    'toast.generated': 'تم إنشاء الجدول',
    'toast.generatedSub': 'تم وضع {shifts} في {seconds} ثانية · التوازن {balance}%',
    'toast.saved': 'تم حفظ الجدول',
    'toast.failed': 'تعذّر إنشاء الجدول',
    'toast.editRefused': 'تم رفض التعديل',
    'toast.retuned': 'أُعيد الضبط حول لياليك المثبّتة',
    'toast.demo': 'تم تحميل القسم التجريبي',
    'toast.demoSub': '10 أطباء، 2 مناوبان كل ليلة، فترتا إجازة وعطلة رسمية واحدة.',
    'toast.restored': 'تمت استعادة الجدول',
    'toast.downloaded': 'تم التنزيل',
    'toast.copied': 'تم النسخ',
    'toast.clipboardBlocked': 'الحافظة محظورة',

    'valid.ok': 'هذا الجدول صالح',
    'valid.okSub': 'التغطية والإجازات والراحة كلها مطابقة لقواعد القسم.',
    'valid.warnNote': 'التنبيهات لا تمنع النشر.',

    'unit.night': '{count} ليلة',
    'unit.doctor': '{count} طبيب',
    'unit.shift': '{count} مناوبة',
    'unit.rota': '{count} جدول',
  },
};

/* Plural forms that the `{count} x` keys need per language. English and
   French have two; Arabic has six, so the counted nouns are spelled out
   rather than pluralised by appending an "s". */
const PLURALS = {
  en: {
    'unit.night': { one: '{count} night', other: '{count} nights' },
    'unit.doctor': { one: '{count} doctor', other: '{count} doctors' },
    'unit.shift': { one: '{count} shift', other: '{count} shifts' },
    'unit.rota': { one: '{count} rota', other: '{count} rotas' },
    'rules.holidays': { one: '{count} holiday', other: '{count} holidays' },
    'share.views': { one: '{count} view', other: '{count} views' },
  },
  fr: {
    'unit.night': { one: '{count} nuit', other: '{count} nuits' },
    'unit.doctor': { one: '{count} médecin', other: '{count} médecins' },
    'unit.shift': { one: '{count} garde', other: '{count} gardes' },
    'unit.rota': { one: '{count} planning', other: '{count} plannings' },
    'rules.holidays': { one: '{count} jour férié', other: '{count} jours fériés' },
    'share.views': { one: '{count} vue', other: '{count} vues' },
  },
  ar: {
    'unit.night': {
      zero: 'لا ليالي', one: 'ليلة واحدة', two: 'ليلتان',
      few: '{count} ليالٍ', many: '{count} ليلة', other: '{count} ليلة',
    },
    'unit.doctor': {
      zero: 'لا أطباء', one: 'طبيب واحد', two: 'طبيبان',
      few: '{count} أطباء', many: '{count} طبيبًا', other: '{count} طبيب',
    },
    'unit.shift': {
      zero: 'لا مناوبات', one: 'مناوبة واحدة', two: 'مناوبتان',
      few: '{count} مناوبات', many: '{count} مناوبة', other: '{count} مناوبة',
    },
    'unit.rota': {
      zero: 'لا جداول', one: 'جدول واحد', two: 'جدولان',
      few: '{count} جداول', many: '{count} جدولًا', other: '{count} جدول',
    },
    'rules.holidays': {
      zero: 'لا عطل رسمية', one: 'عطلة رسمية واحدة', two: 'عطلتان رسميتان',
      few: '{count} عطل رسمية', many: '{count} عطلة رسمية', other: '{count} عطلة رسمية',
    },
    'share.views': {
      zero: 'لا مشاهدات', one: 'مشاهدة واحدة', two: 'مشاهدتان',
      few: '{count} مشاهدات', many: '{count} مشاهدة', other: '{count} مشاهدة',
    },
  },
};

let current = 'en';
let pluralRules = new Intl.PluralRules('en-GB');

export function setLocale(code) {
  current = CATALOG[code] ? code : 'en';
  pluralRules = new Intl.PluralRules(LOCALES[current].intl);
  document.documentElement.lang = current;
  document.documentElement.dir = LOCALES[current].dir;
  return current;
}

export const locale = () => current;
export const direction = () => LOCALES[current].dir;
export const intlTag = () => LOCALES[current].intl;

function interpolate(template, vars) {
  return String(template).replace(/\{(\w+)\}/g, (whole, key) =>
    (key in vars ? String(vars[key]) : whole));
}

/** Translate a key. Falls back to English, then to the key itself. */
export function t(key, vars = {}) {
  const table = PLURALS[current]?.[key];
  if (table && 'count' in vars) {
    const form = table[pluralRules.select(Number(vars.count))] || table.other;
    return interpolate(form, vars);
  }
  const text = CATALOG[current]?.[key] ?? CATALOG.en[key] ?? key;
  return interpolate(text, vars);
}

/* ── locale-aware formatting ─────────────────────────────────────
   Dates and numbers come from Intl so Arabic gets its own month
   names and French its comma decimal separator, rather than English
   strings with translated labels bolted on. */

export const num = (value, digits = 1) =>
  new Intl.NumberFormat(intlTag(), { maximumFractionDigits: digits }).format(value);

export function fmtDate(iso, opts = { weekday: 'short', day: 'numeric', month: 'short' }) {
  const d = new Date(`${iso}T00:00:00`);
  return new Intl.DateTimeFormat(intlTag(), opts).format(d);
}

export function monthLabel(year, monthIndex) {
  return new Intl.DateTimeFormat(intlTag(), { month: 'long', year: 'numeric' })
    .format(new Date(year, monthIndex, 1));
}

/** Weekday names in the locale, Sunday first to match the calendar grid. */
export function weekdayNames(style = 'short') {
  const fmt = new Intl.DateTimeFormat(intlTag(), { weekday: style });
  // 2023-01-01 was a Sunday.
  return Array.from({ length: 7 }, (_, i) => fmt.format(new Date(2023, 0, 1 + i)));
}

/** Apply translations to any element carrying data-i18n in the markup. */
export function translateDom(root = document) {
  for (const node of root.querySelectorAll('[data-i18n]')) {
    node.innerHTML = t(node.dataset.i18n);
  }
  for (const node of root.querySelectorAll('[data-i18n-placeholder]')) {
    node.placeholder = t(node.dataset.i18nPlaceholder);
  }
  for (const node of root.querySelectorAll('[data-i18n-title]')) {
    node.title = t(node.dataset.i18nTitle);
  }
  for (const node of root.querySelectorAll('[data-i18n-aria]')) {
    node.setAttribute('aria-label', t(node.dataset.i18nAria));
  }
}

export function detectLocale(stored) {
  if (stored && CATALOG[stored]) return stored;
  for (const tag of navigator.languages || [navigator.language || 'en']) {
    const code = String(tag).slice(0, 2).toLowerCase();
    if (CATALOG[code]) return code;
  }
  return 'en';
}
