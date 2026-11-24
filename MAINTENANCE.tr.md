# CAMed bakım notları

[English](MAINTENANCE.md)

## FreeCAD’de gerekli değişiklikler ve CAMed’e etkileri

CAMed, FreeCAD’in G-code editörünü, stok ve takım araçlarını, delme çevrimi
üreticisini ve OpenGL simülatörünü kullanır. Simülatörün Python arayüzündeki
iki değişiklik, kameraları eşitlemeyi mümkün kılar ve satıra gitme özelliğinin
bakım yükünü azaltır.

- **Kamera eşitleme.** FreeCAD, simülatör kamerasını Python üzerinden okumaya,
  ayarlamaya ve kamera değişikliklerini izlemeye izin vermeli. Böylece CAMed,
  normal 3B görünüm ve simülatör arasında döndürme, kaydırma ve yakınlaştırmayı
  iki yönlü eşitleyebilir. Simülatör stoğu ekrana sığdırdığında normal 3B
  görünüm de aynı kadraja geçebilir.
- **G-code satırına gitme.** FreeCAD, gönderilen her komutun son simülasyon
  adımını Python üzerinden vermeli. Şu anda her kaynak satırının bittiği adımı
  `timeline.py` hesaplıyor. `MillPathSegment` veya `MillSimulation` adım hesabı
  değiştiğinde bu eşlemeyi kontrol etmek gerekiyor. FreeCAD bu bilgiyi sağlarsa
  CAMed, seçili satırdan üretilen son komutun son adımına doğrudan gidebilir ve
  kendi adım hesabını kaldırabilir.

## Testler

Testler eklenti kökünden çalıştırılır:

```text
python -B -m unittest discover -s tests -q
```

FreeCAD'in Python ortamında ayrıca `tests/run_qt_checks.py` ve
`tests/run_freecad_checks.py` çalıştırılır. Qt testleri ayrı ekran dışı ortamda
çalışır; kullanıcının açık FreeCAD oturumunu kullanmaz. Ortamın Qt eklenti dizini
`QT_PLUGIN_PATH` ile tanımlanmalıdır. Normal Python'da native çevrim testleri için
`FREECAD_CAM_ROOT`, FreeCAD'in `Mod/CAM` dizinini gösterebilir.

[Çeviri bakımı](freecad/camed/resources/translations/README.tr.md)
