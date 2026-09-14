<%"---"%>
created: <% tp.file.creation_date() %>
tags:
fileClass: project
hd: 
MondayCom_nr:
Datalab_nr:
alias: 
rol:
start-project:
eind-project:
tasks: true
<%"---"%>
<% await tp.file.move("/d5 WDODelta/40-49 Taken en ideeën/43 Projecten 2023-2026/" + tp.file.title) %>
[[!d5_Projecten WDOD-MOC]]

> [!todo] Eerst: chase of skip? Maak [[Besluit chase-of-skip]] — de drie poorten: wie vangt het op? / past het binnen het deel? / landt het?


> [!info] status, rol en datums
>  Status: `&=choice(this.projectstatus, this.projectstatus, "")`
> Rol: `&=choice(this.rol, this.rol, "")`
> Startdatum: `&=choice(this.start-project, this.start-project, "")`
> Einddatum: `&=choice(this.eind-project, this.eind-project, "")`

# Doel en toelichting

# Project meta data

## Betrokken

**Opdrachtgever:** 
**Gebruikers:** 
**PO/Projectleider:** 
**Specialisten:** 
**Adviseurs:** 
**Adviesbureaus:** 

## Locaties bestanden

**Lokaal:** 
**Netwerk:**
**Mail:** 
**Scripts:** 
**Modellen:** 
**GIS:** 
**Notities:** 

## Relevante project codes

| Platform       | Code                                                |
| -------------- | --------------------------------------------------- |
| Datalab        | `&=choice(this.Datalab_nr, this.Datalab_nr, "")`     |
| Monday.com     | `&=choice(this.MondayCom_nr, this.MondayCom_nr, "")` |
| Jelle Deciamal | `&=choice(this.hd, this.hd, "")`                     |



# Overleggen en afspraken


# Gerelateerde notities

```dataview
TABLE 
WHERE hd = this.hd AND file.name != this.file.name
SORT file.name
LIMIT 25
```

# Tasks

> Import template 'Project afronding WDODelta' bij afsluiten project

- [ ] zet project id in tabel en onder 'jd' en 'alias'. 🆔 mqjpKx
- [ ] maak freefilesync aan van Obsidian note naar projectmap 🆔 pUFo5P


