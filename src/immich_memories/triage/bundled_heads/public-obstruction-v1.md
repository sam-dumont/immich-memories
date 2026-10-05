# Public finger-over-the-lens probe

`public-obstruction-v1.npz` is a per-patch logistic probe over DINOv2-small patch tokens, trained by `scripts/triage_heads/obstruction/train.py` with a fixed seed (0). It contains no owner photograph, no owner-derived weight, and no identity. SHA-256: `2a7dccdcef7ad3960b99f473021f4ce448a3b3ad2453f3e8a7e11c1bfd1855ed`.

## Positives: synthetic composites on public negatives

Each positive is one of the Commons negatives below with a defocused, skin-toned shape pasted over a random edge (`_composite_finger`): 1-2 strokes, random width, length, entry edge and skin tone, Gaussian-blurred to a soft boundary, with Gaussian pixel noise. The per-pixel alpha is the training label, downsampled to the 16x16 patch grid; a patch is a positive example above alpha 0.5, a negative below 0.1, and dropped in between.

## Negatives and composite bases: Commons images

| file | license | page |
|---|---|---|
| 0042297849.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Vihorlat_(v_zime)_046.jpg |
| 0052203704.jpg | CC BY-SA 2.0 | https://commons.wikimedia.org/wiki/File:2003_11_28_50._Geburtstag_099_(51035631853).jpg |
| 0067630124.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Delicious_slice_of_cake_with_cream.jpg |
| 0076156909.jpg | Public domain | https://commons.wikimedia.org/wiki/File:1905-08-08_Kuche_in_Durerhaus_A.jpg |
| 0089373259.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:2023050103_Acker-Vergissmeinnicht_drei_Blueten_Blende_8,0_gruener_Hintergrund_(Wiese)_2023.jpg |
| 0098824206.jpg | CC BY-SA 3.0 | https://commons.wikimedia.org/wiki/File:Centre_nautique_de_Saint-Joseph.jpg |
| 0144866182.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:202311_Hemidactylus_bowringii(Oriental_leaf-toed_gecko)_was_set_on_the_AC_power_plug_of_dusty.jpg |
| 0175444661.jpg | CC0 | https://commons.wikimedia.org/wiki/File:Dry_chemical_powder_fire_suppression_in_shop.jpg |
| 0213993735.jpg | CC BY 3.0 | https://commons.wikimedia.org/wiki/File:500px_photo_(105267573).jpeg |
| 0236171835.jpg | CC BY-SA 3.0 de | https://commons.wikimedia.org/wiki/File:Bundesarchiv_Bild_183-U0314-013,_Betreung_behinderter_Kinder_in_einer_Jenaer_Krippe.jpg |
| 0242079693.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:A_curious_baby_lies_on_a_floral_blanket,_reaching_for_a_colorful_toy_microphone_held_by_a_caretaker.jpg |
| 0247818818.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:%22Seguimi%22.jpg |
| 0251798469.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:All_E_Technologies_Ltd_NSE_Event_-_2.jpg |
| 0262915334.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Canandaigua_Lake_Squaw_Island_Water_Biscuits.jpg |
| 0327903101.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:120410_Khumbu_Glacier_Pano.jpg |
| 0349451182.jpg | CC BY 3.0 | https://commons.wikimedia.org/wiki/File:08062012_-_panoramio.jpg |
| 0364252166.jpg | CC BY 3.0 | https://commons.wikimedia.org/wiki/File:2010.04.05.12.10.30.JPG |
| 0380069375.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:1_lake_louise_pano_2019.jpg |
| 0406105535.jpg | CC BY 4.0 | https://commons.wikimedia.org/wiki/File:141_Desfent_la_catifa_de_Corpus,_parc_de_Sant_Mart%C3%AD_(Barcelona).jpg |
| 0408244155.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Ceiling_decorated_in_national_style.jpg |
| 0411990549.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Nicely_arranged_cutlery_for_a_birthday.jpg |
| 0414631458.jpg | CC BY 3.0 | https://commons.wikimedia.org/wiki/File:Ancient_Gateway_(116650393).jpeg |
| 0418218501.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Children_playing_outdoors_on_birthday_party_in_garden_in_spring._Back_view_of_children._(51159149625).jpg |
| 0433393684.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:-365_monkeyBars_(21665576909).jpg |
| 0470973757.jpg | CC BY 4.0 | https://commons.wikimedia.org/wiki/File:Arab_pharmacy,_view_of_front_door_Wellcome_L0011526.jpg |
| 0518378247.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Puente_de_Olaranbe_05.jpg |
| 0537747385.jpg | CC BY-SA 2.5 | https://commons.wikimedia.org/wiki/File:Schaufensterglanz4.JPG |
| 0555640633.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:8527-Brier-Dr-1.jpg |
| 0569988394.jpg | Public domain | https://commons.wikimedia.org/wiki/File:Prince%27s_Day,_by_Jan_Steen.jpg |
| 0578809415.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:In_a_charming_outdoor_space,_a_young_boy_sits_beside_a_toddler_girl_on_a_natural_rug.jpg |
| 0589749382.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Camera_dubla_nr_4.jpg |
| 0600237854.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Acceso_Direccion_de_Informacion_y_Estudios_Economicos.jpg |
| 0627080331.jpg | CC BY-SA 2.0 | https://commons.wikimedia.org/wiki/File:Child%27s_bedroom_(427382851).jpg |
| 0654210710.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Kot_loki.jpg |
| 0660537371.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:4.pic.jpg |
| 0705588885.jpg | Copyrighted free use | https://commons.wikimedia.org/wiki/File:Bossenmauerwerk.jpg |
| 0709961525.jpg | CC0 | https://commons.wikimedia.org/wiki/File:A_zoomed_up_picture_of_an_orange_(cropped).jpg |
| 0710832976.jpg | CC BY-SA 3.0 | https://commons.wikimedia.org/wiki/File:2010-03-06_%D0%91%D0%B0%D1%81%D1%82%D0%B8%D0%BE%D0%BD_%D0%BE%D0%B3%D1%80%D0%B0%D0%B6%D0%B4%D0%B5%D0%BD%D0%B8%D1%8F_%D0%BF%D0%BB%D0%BE%D1%89%D0%B0%D0%B4%D0%B8_%D0%91%D0%BE%D0%BB%D1%8C%D1%88%D0%BE%D0%B3%D0%BE_%D0%93%D0%B0%D1%82%D1%87%D0%B8%D0%BD%D1%81%D0%BA%D0%BE%D0%B3%D0%BE_%D0%B4%D0%B2%D0%BE%D1%80%D1%86%D0%B0.jpg |
| 0732280797.jpg | CC BY-SA 2.0 | https://commons.wikimedia.org/wiki/File:Blue_is_the_colour_(8543350706).jpg |
| 0746300185.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Aerial_View_of_a_city_in_night.1.jpg |
| 0748132818.jpg | CC0 | https://commons.wikimedia.org/wiki/File:Kuih_batang_buruk.jpg |
| 0791379252.jpg | CC BY-SA 2.0 | https://commons.wikimedia.org/wiki/File:Kisses_(3408686106).jpg |
| 0798015901.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Baltic_Queen,_20221216_12.jpg |
| 0851057438.jpg | Attribution | https://commons.wikimedia.org/wiki/File:381._Gheorghiu_Dej_birthday.jpg |
| 0884022661.jpg | Public domain | https://commons.wikimedia.org/wiki/File:171021-Z-YI114-077_(38012987732).jpg |
| 0887108693.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:20150201CAT_BA_MTB19.jpg |
| 0890878916.jpg | CC BY-SA 2.0 | https://commons.wikimedia.org/wiki/File:A_misty_day_in_nature_(32436544564).jpg |
| 0911087083.jpg | CC BY 3.0 | https://commons.wikimedia.org/wiki/File:2013-01-17_12-43-45-neige-13f.jpg |
| 0956352325.jpg | Public domain | https://commons.wikimedia.org/wiki/File:Baldomer_Gili_Roig._Menjador.jpg |
| 0969569890.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:AanDeZweth-feb2021-2.jpg |
| 1049384285.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:D%C3%BClmen,_Hausd%C3%BClmen,_Sonnenaufgang_--_2015_--_4952.jpg |
| 1060517707.jpg | CC BY-SA 2.0 | https://commons.wikimedia.org/wiki/File:Boats_leave_hartford_independence_day_fireworks_show_-_Flickr_-_TonySprezzatura.jpg |
| 1086419374.jpg | Public domain | https://commons.wikimedia.org/wiki/File:Cosmeticsrazorback.jpg |
| 1127440384.jpg | CC BY-SA 3.0 | https://commons.wikimedia.org/wiki/File:Cine%27nin_meshur_k%C3%B6ftecileri_(01.01.2010)_-_panoramio.jpg |
| 1129900891.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:A_dark_chocolate_christmas_tree.jpg |
| 1169861260.jpg | CC BY 3.0 | https://commons.wikimedia.org/wiki/File:Bike_park_in_T%C5%99eb%C3%AD%C4%8D,_T%C5%99eb%C3%AD%C4%8D_District.jpg |
| 1199006914.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:A_person_is_opening_a_door_to_enter_a_room_with_soft_lighting_and_wooden_floor_at_home.jpg |
| 1205965469.jpg | CC BY-SA 3.0 | https://commons.wikimedia.org/wiki/File:Dan_Atherton_Sea_Otter_2009_Dual_Slalom.JPG |
| 1221029941.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Katzen_in_Passelsberg_02.jpg |
| 1268814652.jpg | CC BY-SA 3.0 | https://commons.wikimedia.org/wiki/File:2013._The_TCL_Chinese_Theatre_-_panoramio.jpg |
| 1311331025.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Atmosphere_-_Flickr_-_%E3%81%91%E3%82%93%E3%81%9F%E3%81%BE-KENTAMA.jpg |
| 1327003980.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Little_baby_girl_reading_a_book_on_the_bed.jpg |
| 1352203277.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:%22%E0%B9%80%E0%B8%9B%E0%B8%B4%E0%B8%94%22_%E0%B8%93_%E0%B8%A3%E0%B8%B1%E0%B8%90%E0%B8%AA%E0%B8%A0%E0%B8%B2%E0%B8%8D%E0%B8%B5%E0%B9%88%E0%B8%9B%E0%B8%B8%E0%B9%88%E0%B8%99_6%E0%B8%9E%E0%B8%A4%E0%B8%A8%E0%B8%88%E0%B8%B4%E0%B8%81%E0%B8%B2%E0%B8%A2%E0%B8%992552_(The_Official_Site_of_The_Prime_Minister_of_Thailand_Photo_by_%E0%B8%9E%E0%B8%B5%E0%B8%A3%E0%B8%9E%E0%B8%B1%E0%B8%92%E0%B8%99%E0%B9%8C_-_Flickr_-_Abhisit_Vejjajiva.jpg |
| 1359917039.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Cozy_bedroom_with_a_large_bed_and_simple_decor_in_a_modern_home.jpg |
| 1389207997.jpg | CC BY 3.0 | https://commons.wikimedia.org/wiki/File:500px_photo_(59503058).jpeg |
| 1408027810.jpg | CC0 | https://commons.wikimedia.org/wiki/File:202505_Taipei_Zoo_flag_flying_01.jpg |
| 1438084166.jpg | CC0 | https://commons.wikimedia.org/wiki/File:Bicycle_Forest_Cannock_(Unsplash).jpg |
| 1442894102.jpg | CC0 | https://commons.wikimedia.org/wiki/File:-i---i-_(16430485236).jpg |
| 1454717311.jpg | Public domain | https://commons.wikimedia.org/wiki/File:Neues_Reich._Dynastie_XX._Med%C3%AEnet_H%C3%A2bu._Grosser_Tempel-_a_-_d._Zweiter_Hof,_(a-c.)_Hinterwand,_(d.)_Pfeiler;_e._f._Aeussere_Nordwand_(NYPL_b14291191-38389).jpg |
| 1459208673.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Chili_preparation_in_a_large_pot_at_a_gathering.jpg |
| 1469109685.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Chicken_Republic_2.jpg |
| 1483866628.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Bedroom_Winchester_Mystery_House_with_pictures.jpg |
| 1685330577.jpg | CC BY 4.0 | https://commons.wikimedia.org/wiki/File:A_brick_wall_at_night_in_Galabovo.jpg |
| 1737532028.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:CAM-Melong-_Hotel_toiture_de_la_case.jpg |
| 1743913913.jpg | CC BY 3.0 | https://commons.wikimedia.org/wiki/File:Alinkor_Island_In_Al_Hoceima_(188452557).jpeg |
| 1755360313.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:2023_%EB%93%B1%EA%B5%A3%EA%B8%B8_%EC%9D%8C%EC%95%85%ED%9A%8C2.jpg |
| 1765295053.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:A.J.M._van_Nispen_tot_Pannerden.jpg |
| 1799778130.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Bandeja_de_comida_t%C3%ADpica_Panam%C3%A1.jpg |
| 1807010166.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Banane_frecinette-1.jpg |
| 1821547476.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Alstroemeria_Macro_-_HDR_(13754166805).jpg |
| 1847881762.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:4Pantai_Dalit_bj.jpg |
| 1873305824.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:-i---i-_(2207789059).jpg |
| 1959394729.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:20150201CAT_BA_MTB9_7016s.jpg |
| 2012691952.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Armoury_Doors_c.1896_$2400_(15195579975).jpg |
| 2013734628.jpg | CC BY-SA 2.5 | https://commons.wikimedia.org/wiki/File:LippenStudium3.JPG |
| 2030560405.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Cute_toddler_enjoying_playtime_while_sitting_in_a_stroller_and_holding_a_colorful_toy_during_a_cozy_indoor_afternoon.jpg |
| 2038834079.jpg | CC BY-SA 3.0 | https://commons.wikimedia.org/wiki/File:Babybuch_startbild.jpg |
| 2048545679.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Camera_dublanr_6.jpg |
| 2085081038.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Bucuresti,_Romania._Pregatiri_de_Craciun._5_decembrie_2022._(2).jpg |
| 2085485833.jpg | CC0 | https://commons.wikimedia.org/wiki/File:Catonwall.jpg |
| 2112195231.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Birthday_Party,_San_Juan_Bautista,_Nueva_Esparta,_Venezuela.jpg |
| 2132003205.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:3XDE9753.jpg |
| 2165353433.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Dolly_Varden_Cake_(cropped).jpg |
| 2172509823.jpg | Public domain | https://commons.wikimedia.org/wiki/File:242-EB-10-8A_-_DPLA_-_37da525b7273f9bb92a83d321280f50a.jpg |
| 2203811623.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Haroon_baby.jpg |
| 2219979642.jpg | CC BY-SA 3.0 de | https://commons.wikimedia.org/wiki/File:Bundesarchiv_Bild_183-71925-0005,_Sarnow,_Blick_in_die_Kinderkrippe.jpg |
| 2231735745.jpg | CC BY 3.0 | https://commons.wikimedia.org/wiki/File:500px_photo_(56240448).jpeg |
| 2263469776.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:20240812_Slow_shutter_shot_toward_the_ocean_from_the_window_inside_of_cruise_oceanview_room_with_camera_at_midnight.jpg |
| 2277568503.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Child_in_swim_goggles_adjusts_mask_near_pool_on_a_sunny_day.jpg |
| 2310473534.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Apparatus_Valve_Assembly.jpg |
| 2316602726.jpg | No restrictions | https://commons.wikimedia.org/wiki/File:Drawing_room,_showing_furniture_(21398961540).jpg |
| 2373768164.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:%22%D0%94%D1%8B%D0%BC%D0%BA%D0%B0%22-_%D0%BF%D0%B0%D1%80%D0%BD%D0%B8_%D0%B2_%D0%BA%D0%BE%D1%81%D0%BE%D0%B2%D0%BE%D1%80%D0%BE%D1%82%D0%BA%D0%B0%D1%85.jpg |
| 2410869859.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Brombeerblatt-5823.jpg |
| 2431471466.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Alcove_-_Flickr_-_hnt6581.jpg |
| 2435896260.jpg | CC BY 3.0 | https://commons.wikimedia.org/wiki/File:500px_photo_(23766577).jpeg |
| 2462854901.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Ceiling_and_partial_window_inside_Karpeles_Manuscript_Library_Museum_in_Jacksonville,_FL_-_February_3,_2023.jpg |
| 2469673248.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Kamalapur_Railway_Station_during_Eid_Ul_Fitr_2026_196.jpg |
| 2480292936.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Hamon_bulakenya_Kaluto.jpg |
| 2483501302.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Basic_Malek_Mansion.jpg |
| 2483642715.jpg | CC0 | https://commons.wikimedia.org/wiki/File:A_portrait_of_a_lady.jpg |
| 2526663595.jpg | CC BY-SA 2.5 | https://commons.wikimedia.org/wiki/File:OrangeOrange_B%C3%B6hringer_1.JPG |
| 2558630247.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:20150201CAT_BA_MTB34.jpg |
| 2616366717.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Antifire_Doors.jpg |
| 2621308743.jpg | Public domain | https://commons.wikimedia.org/wiki/File:(FROM_THE_DOCUMERICA-1_EXHIBITION._FOR_OTHER_IMAGES_IN_THIS_ASSIGNMENT,_SEE_FICHE_NUMBERS_87,_88,_106,_107,_108,_109..._-_NARA_-_552940.jpg |
| 2639193072.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:%22%D0%94%D1%8B%D0%BC%D0%BA%D0%B0%22-%D1%82%D0%B0%D0%BD%D0%B5%D1%86_%D0%B2_%D0%BA%D0%BE%D1%81%D0%BE%D0%B2%D0%BE%D1%80%D0%BE%D1%82%D0%BA%D0%B0%D1%85.jpg |
| 2639228624.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:MEHNDI-93.jpg |
| 2652761305.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Children%27s_games_%D8%A8%D8%A7%D8%B2%DB%8C_%D9%87%D8%A7%DB%8C_%DA%A9%D9%88%D8%AF%DA%A9%D8%A7%D9%86_04.jpg |
| 2654179503.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:2016_366_38_Reach_(24255197734).jpg |
| 2673382814.jpg | Public domain | https://commons.wikimedia.org/wiki/File:Airstyle.jpg |
| 2678316135.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:A_young_girl_stands_at_a_kitchen_table,_wearing_a_fluffy_sweater_and_an_apron.jpg |
| 2691627479.jpg | CC BY-SA 2.0 | https://commons.wikimedia.org/wiki/File:Eldery_Woman_Begging_in_Granada,_Nicaragua_(6570150995).jpg |
| 2693649872.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Adomi.jpg |
| 2693793754.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:20190713_boats_leave_hartford_independence_day_fireworks_show_9UV9491.jpg |
| 2747771390.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:90._sz%C3%BClinap.jpg |
| 2752365061.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Chopping_fresh_ingredients_for_a_flavorful_dish_in_a_rustic_outdoor_kitchen.jpg |
| 2771318221.jpg | CC0 | https://commons.wikimedia.org/wiki/File:Ahsan_Mahim_in_Dhanmondi_in_2024.jpg |
| 2796280442.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:1pantai_Shahbandar_bj.jpg |
| 2805414394.jpg | Public domain | https://commons.wikimedia.org/wiki/File:17th_century_portrait_of_Giovan_Battista_Nicolosi.jpg |
| 2807924470.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:9Y3A0940_(1).jpg |
| 2828018830.jpg | CC BY-SA 2.0 | https://commons.wikimedia.org/wiki/File:2009_LAAFF_108_-_3914993447.jpg |
| 2897462387.jpg | CC BY-SA 3.0 | https://commons.wikimedia.org/wiki/File:BB-Wiegenhaltung.jpg |
| 2933014441.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:-i---i-_(2207742847).jpg |
| 2939799473.jpg | CC BY 3.0 | https://commons.wikimedia.org/wiki/File:Amtrak_To_Chicago_(161317685).jpeg |
| 2964523070.jpg | Public domain | https://commons.wikimedia.org/wiki/File:%27Island_Warriors%27_take_break_from_surf_to_ski_130403-M-NP085-004.jpg |
| 2977297684.jpg | CC BY-SA 3.0 | https://commons.wikimedia.org/wiki/File:Carnival_snowboard_session_Rijeka_26012013_2_roberta_f.jpg |
| 2979127778.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:At_Tenerife_2022_476.jpg |
| 2981846125.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Adam_Ibrahim_Fouad_portrait_2026.jpg |
| 3023441116.jpg | CC BY 4.0 | https://commons.wikimedia.org/wiki/File:ABAL1412_(2025).jpg |
| 3025612173.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:20150201CAT_BA_MTB16.jpg |
| 3057504824.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Jankuno.jpg |
| 3063367644.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Child_in_a_red_vest_being_held_outdoors_by_an_adult_in_a_patterned_shirt.jpg |
| 3086452444.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Dificultades_y_retos.jpg |
| 3088692037.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Children_play_Row,_Row,_Row_Your_Boat.jpg |
| 3094531722.jpg | CC BY-SA 2.0 | https://commons.wikimedia.org/wiki/File:A_misty_day_in_nature_(32115901873).jpg |
| 3121773809.jpg | CC BY 4.0 | https://commons.wikimedia.org/wiki/File:07042024-DSC_5372.jpg |
| 3128881687.jpg | CC BY-SA 3.0 | https://commons.wikimedia.org/wiki/File:Boardjacket.JPG |
| 3150271603.jpg | CC0 | https://commons.wikimedia.org/wiki/File:12am_photos_23.jpg |
| 3164496351.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Karupuak_Kuah_Mie.jpg |
| 3168081923.jpg | CC BY-SA 2.5 | https://commons.wikimedia.org/wiki/File:Ruhender_B%C3%B6hringer.JPG |
| 3203408002.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Fat_air.jpg |
| 3246669551.jpg | Public domain | https://commons.wikimedia.org/wiki/File:2_Lt_Marsh_(Miss_America)_at_Daytona_500_8245232.jpg |
| 3298074796.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Coppa2.jpg |
| 3308152662.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:3Pantai_Dalit_bj.jpg |
| 3343748822.jpg | CC0 | https://commons.wikimedia.org/wiki/File:Broparken,_Ume%C3%A5.JPG |
| 3361047581.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:20150201CAT_BA_MTB10.jpg |
| 3395784346.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Complete_Pediatric_Belt_Cane_set.jpg |
| 3431985385.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:-i---i-_(2207896351).jpg |
| 3462322730.jpg | CC BY-SA 3.0 | https://commons.wikimedia.org/wiki/File:Ceiling_1_(138191783).jpeg |
| 3507666588.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Ezh9MCdBLEg.jpg |
| 3541367330.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:5_Porta_Blava02.jpg |
| 3544073008.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Hand_Story.jpg |
| 3553797274.jpg | CC0 | https://commons.wikimedia.org/wiki/File:2%C3%A8me_photo_de_Vince.jpg |
| 3557727262.jpg | CC BY-SA 3.0 | https://commons.wikimedia.org/wiki/File:Assentamento_com_argamassa_polim%C3%A9rica.JPG |
| 3575485919.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Glacier_de_Mont-de-Lans_-_France_-_2020.jpg |
| 3673209193.jpg | CC BY-SA 2.0 | https://commons.wikimedia.org/wiki/File:Bar_Doors_in_Lijiang.jpg |
| 3708262471.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Diving_(43551152290).jpg |
| 3709017340.jpg | CC BY-SA 3.0 | https://commons.wikimedia.org/wiki/File:Birthday_party_gumballs_2.jpg |
| 3725131985.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:34_Tomba_Brion_-_San_Vito_d%27Altivole,_Treviso,_Italy_-_Carlo_Scarpa-FPPL3001.jpg |
| 3734848544.jpg | Public domain | https://commons.wikimedia.org/wiki/File:Bodleian_Libraries,_Delights_of_Islington.jpg |
| 3735037644.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:2024_closingconcert.jpg |
| 3795181264.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:DinerQuartier.jpg |
| 3796716415.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Baby_in_striped_onesie_being_held_comfortably_by_caregiver_in_a_cozy_indoor_setting_during_daytime.jpg |
| 3810493604.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:2014-07-03_13.56.10_Locos_Mayo.jpg |
| 3818394998.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:1st_Portrait_of_Priyangika_Karannagoda.jpg |
| 3825463765.jpg | CC0 | https://commons.wikimedia.org/wiki/File:Cats0005.jpg |
| 3858011368.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:23_Independence_Avenue%E2%80%A6.By_Night.jpg |
| 3955300643.jpg | Public domain | https://commons.wikimedia.org/wiki/File:673rd_FSS_hosts_2014_Spring_Meltdown_event_140322-F-XA488-106.jpg |
| 3969574991.jpg | CC BY-SA 3.0 | https://commons.wikimedia.org/wiki/File:1988_jimmy_deaton_john_tomac_dual_slalom_mammoth_mtn.jpg |
| 3992178391.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Moroccan_Birthday_party-01.jpg |
| 3995441662.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:20241223_tazza_di_bokeh_PD104669.jpg |
| 3997869388.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Cozy_bedroom_with_two_beds_window_and_wall_art_in_a_simple_setting.jpg |
| 4022764854.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:2025-05-08_11_54_07_Kitchen_and_dining_area_within_Playpad_Bucks_in_Middletown_Township,_Bucks_County,_Pennsylvania.jpg |
| 4122060361.jpg | CC BY-SA 3.0 | https://commons.wikimedia.org/wiki/File:Affresco_4_Carditello.jpg |
| 4130228488.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:20150201CAT_BA_MTB3.jpg |
| 4193497475.jpg | CC0 | https://commons.wikimedia.org/wiki/File:-i---i-_(16269113470).jpg |
| 4216417482.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Budapest_ceiling_detail_(16268852999).jpg |
| 4220728730.jpg | CC BY-SA 2.0 | https://commons.wikimedia.org/wiki/File:Asymmetri_(9168845264).jpg |
| 4285846789.jpg | No restrictions | https://commons.wikimedia.org/wiki/File:American_Starch_Co._(3093855224).jpg |
| 4287414568.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Blue_and_gold_door,_Shoreditch_(33493754336).jpg |
| 4320917815.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:AR0A4251.jpg |
| 4349077106.jpg | CC BY-SA 3.0 | https://commons.wikimedia.org/wiki/File:Brownlee_Nannys_State.jpg |
| 4350062515.jpg | CC BY-SA 3.0 | https://commons.wikimedia.org/wiki/File:Blood_on_my_hands.JPG |
| 4372338246.jpg | CC BY-SA 3.0 pl | https://commons.wikimedia.org/wiki/File:8_BA%C5%BBANTARNIA.JPG |
| 4376378928.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Aristidek5maya_at_Wikimania_2023.jpg |
| 4388375214.jpg | CC BY 4.0 | https://commons.wikimedia.org/wiki/File:Brincando_na_fonte_interativa_do_Lago_Municipal_de_Araras.jpg |
| 4411639510.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:0%D8%B9%DB%8C%D9%88%D8%B6%DB%8C.jpg |
| 4456110791.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Ceiling_and_glass.jpg |
| 4465280004.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Child%27s_hand_and_the_sky_in_the_background.jpg |
| 4492965107.jpg | CC BY-SA 3.0 | https://commons.wikimedia.org/wiki/File:Rick_EY.jpg |
| 4511436149.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Aliyev_prospekti,_Baku_(P1090234).jpg |
| 4519837161.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:17_Abbotsford_Road,_Willowbush,_Boundary_Walls.jpg |
| 4545221152.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Himalaya_Outer_Photos.jpg |
| 4579414918.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Biljne_vrste_u_ni%C5%A1koj_tvr%C4%91avi,_Srbija,_Ni%C5%A1_(92).jpg |
| 4613366411.jpg | CC BY 3.0 | https://commons.wikimedia.org/wiki/File:Banana_Flip_(101554671).jpeg |
| 4670454575.jpg | CC BY 3.0 | https://commons.wikimedia.org/wiki/File:Fastplant_(31905541).jpeg |
| 4698699622.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Ko%C4%8Di%C4%8D%C3%AD_pozdrav.jpg |
| 4727941569.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Chambre_moulin.jpg |
| 4749496490.jpg | CC BY-SA 3.0 | https://commons.wikimedia.org/wiki/File:Elatochori_snowboard_centre.jpg |
| 4781211780.jpg | CC0 | https://commons.wikimedia.org/wiki/File:A_man_stands_next_to_a_road_in_Baidoa,_Somalia,_while_Ethiopian_soldiers_as_part_of_the_African_Union_Mission_in_Somalia,_conduct_a_night_patrol_through_the_city_on_June_22._AMISOM_Photo_-_Tobin_Jones_(14518877355).jpg |
| 4806521771.jpg | CC0 | https://commons.wikimedia.org/wiki/File:%22VONTRIHY_%22_01.jpg |
| 4806953692.jpg | CC0 | https://commons.wikimedia.org/wiki/File:20190617_Nebbia_(2).jpg |
| 4845483335.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:A_Lentinus_mushroom_was_grew_at_the_surface_of_mountain_rock_20240623.jpg |
| 4863966020.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Auberge_du_Kochersberg_-1.jpg |
| 4930675456.jpg | CC BY-SA 3.0 | https://commons.wikimedia.org/wiki/File:Ciampinoi_in_Val_Gardena.jpg |
| 4945311260.jpg | CC BY-SA 3.0 | https://commons.wikimedia.org/wiki/File:2013,_Albuquerque,_View_S,_Rio_Grande_River_-_panoramio.jpg |
| 4961451162.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Birtday_celibration_Nepali_village_child.jpg |
| 4962827911.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:2024_March_CGS_portrait.jpg |
| 5028735783.jpg | Public domain | https://commons.wikimedia.org/wiki/File:Bianchi_pablo.jpg |
| 5039354481.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:15.04.2015_21.44_DSC5688bearbeitet_1.jpg |
| 5047374471.jpg | CC0 | https://commons.wikimedia.org/wiki/File:C171117_(40148382610).jpg |
| 5059039836.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Ceiling_4.jpg |
| 5068777898.jpg | Public domain | https://commons.wikimedia.org/wiki/File:A_photographer_appears_to_be_photographing_himself_in_a_photographic_studio)_-_Wheeler,_Berlin,_Wis_LCCN2004681684.jpg |
| 5095837497.jpg | Public domain | https://commons.wikimedia.org/wiki/File:Birthday_Party._Nairobi._1964.jpg |
| 5120218570.jpg | CC BY-SA 2.0 | https://commons.wikimedia.org/wiki/File:Cabot%27s_Ice_Cream_%26_Restaurant.jpg |
| 5127477942.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:2022_-_Influence_at_Palacio_do_Grilo_RC0_9502_(52473246294).jpg |
| 5147108296.jpg | CC BY 3.0 | https://commons.wikimedia.org/wiki/File:A_pont_t%C3%A9rbeli_%C3%A1br%C3%A1zol%C3%A1sa_-az%C3%A9rt_mert_pont_ott_van._-_panoramio.jpg |
| 5149216096.jpg | CC BY 4.0 | https://commons.wikimedia.org/wiki/File:Ansaldo_Hse_2_-_Indoor.jpg |
| 5150962236.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Beleuchteter_Weihnachtsbaum_am_Stachus_in_M%C3%BCnchen.jpg |
| 5160397648.jpg | CC BY 3.0 | https://commons.wikimedia.org/wiki/File:-_panoramio_(3661).jpg |
| 5162972527.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Deep-fryer-7.jpg |
| 5168843708.jpg | CC BY 4.0 | https://commons.wikimedia.org/wiki/File:Bedroom_with_loft_(2014).jpg |
| 5177172050.jpg | CC BY-SA 2.0 | https://commons.wikimedia.org/wiki/File:All_For_One_-_Flickr_-_jeff_golden.jpg |
| 5187783455.jpg | Public domain | https://commons.wikimedia.org/wiki/File:Horrible_fin_d%27un_Poisson_rouge.jpg |
| 5220946510.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:At_Tenerife_2022_484.jpg |
| 5235780763.jpg | CC BY 3.0 | https://commons.wikimedia.org/wiki/File:240405_Cave_aux_Po%C3%A8tes_%C2%A9Maxime_Szczepanek.jpg |
| 5257435715.jpg | CC BY 4.0 | https://commons.wikimedia.org/wiki/File:A_woman_washing_dishes_to_assist_the_cooks.jpg |
| 5304866079.jpg | CC BY 3.0 | https://commons.wikimedia.org/wiki/File:500px_photo_(45164668).jpeg |
| 5320668086.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Bring_The_Light_(3460404871).jpg |
| 5357652452.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Cartel_Luminoso_Ornella.jpg |
| 5357981475.jpg | CC BY-SA 2.0 | https://commons.wikimedia.org/wiki/File:Changing_a_Nappy.jpg |
| 5364450822.jpg | Public domain | https://commons.wikimedia.org/wiki/File:%27Island_Warriors%27_take_break_from_surf_to_ski_130403-M-NP085-005.jpg |
| 5366545385.jpg | CC BY 4.0 | https://commons.wikimedia.org/wiki/File:2005-02-21_Barbed_wire_with_snow_and_ice.jpg |
| 5383375791.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:GS-0007-FB_Floating_-_Empty_2.jpg |
| 5399696628.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:A_stylish_living_area_features_a_modern_kitchen,_comfortable_seating,_and_large_windows_allowing_ample_natural_ligh.jpg |
| 5434110169.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Children_enjoy_baking_activities_with_dough_and_rolling_pins_in_a_cozy_kitchen_setting_during_a_family_gathering.jpg |
| 5435924615.jpg | CC BY 3.0 | https://commons.wikimedia.org/wiki/File:500px_photo_(140224729).jpeg |
| 5449200524.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Laima_Sultana_Nushra.jpg |
| 5469354728.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:%22%D0%A1%D0%BB%D0%BE%D0%B1%D0%BE%D0%B4%D0%B0%22-_%D1%84%D0%BE%D0%BB%D1%8C%D0%BA%D0%BB%D0%BE%D1%80%D0%BD%D1%8B%D0%B9_%D0%BA%D0%BE%D0%BB%D0%BB%D0%B5%D0%BA%D1%82%D0%B8%D0%B2_%D0%BD%D0%B0%D1%80%D0%BE%D0%B4%D0%BD%D0%BE%D0%B3%D0%BE_%D1%82%D0%B2%D0%BE%D1%80%D1%87%D0%B5%D1%81%D1%82%D0%B2%D0%B0._%D0%9A%D0%B8%D1%80%D0%BE%D0%B2_4.jpg |
| 5504948781.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:8%D0%9A98-%D1%86%D0%B5%D1%85-1.jpg |
| 5521569980.jpg | Public domain | https://commons.wikimedia.org/wiki/File:Abd_el-Ouahed_ben_Messaoud_ben_Mohammed_Anoun,_Moorish_ambassador_to_Elizabeth_I,_who_may_have_been_the_inspiration_for_the_character_Othello_(4004295055).jpg |
| 5524406846.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Compact_ski.jpg |
| 5540560229.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Aydekorasyongroup.jpg |
| 5543137558.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:A_happy_artist.jpg |
| 5549456454.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Blick_vom_Barby-Schloss_auf_die_Laurentiuskirche.jpg |
| 5559731656.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Child_plays_with_a_flower_while_an_adult_sits_nearby_at_a_gathering_in_a_bright_outdoor_setting.jpg |
| 5622165560.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Chopping_fresh_peppers_in_a_rustic_kitchen_during_a_vibrant_cooking_session_in_the_countryside.jpg |
| 5625448506.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:All_knots_and_bells.jpg |
| 5637639048.jpg | CC0 | https://commons.wikimedia.org/wiki/File:Food_photography.snacks.jpg |
| 5640454725.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Ancient_walls.jpg |
| 5651639659.jpg | CC0 | https://commons.wikimedia.org/wiki/File:El_Primo_Sausages_and_Dairy_Factory.jpg |
| 5674374535.jpg | CC BY-SA 2.0 | https://commons.wikimedia.org/wiki/File:2003_11_28_50._Geburtstag_098_(51035630198).jpg |
| 5768028272.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:20150201CAT_BA_MTB32.jpg |
| 5771624946.jpg | CC BY 3.0 | https://commons.wikimedia.org/wiki/File:500px_photo_(14154517).jpeg |
| 5777663150.jpg | CC BY 3.0 | https://commons.wikimedia.org/wiki/File:Chinese_Restaurant_(31906211).jpeg |
| 5785664020.jpg | Public domain | https://commons.wikimedia.org/wiki/File:James_Clise_Jr_with_unidentified_girl,_Redmond,_ca_1903_(MOHAI_2475).jpg |
| 5798794201.jpg | CC BY-SA 3.0 | https://commons.wikimedia.org/wiki/File:Burton_snowboard_bindings_8286690986_o.jpg |
| 5799224658.jpg | Public domain | https://commons.wikimedia.org/wiki/File:Assignment-_48-DPA-9-13-06_K_DOI_Build)_Main_Interior_Building-_(views_from_interior,_exterior_renovation_projects)_(48-DPA-9-13-06_K_DOI_Build_IOD_5613.JPG_-_DPLA_-_487ba33947486898b7c2a103881e7992.JPG |
| 5842705775.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Children_playing_(9309194059).jpg |
| 5849566353.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Claude_Moore_Colonial_Farm_P1010587_(506776392).jpg |
| 5863486527.jpg | Copyrighted free use | https://commons.wikimedia.org/wiki/File:Kitesnowboarding.jpg |
| 5883140942.jpg | CC BY 3.0 | https://commons.wikimedia.org/wiki/File:2013-01-17_12-42-19-neige-12f.jpg |
| 5885787468.jpg | CC0 | https://commons.wikimedia.org/wiki/File:Ceiling_texture.jpg |
| 5894285753.jpg | CC BY-SA 2.0 | https://commons.wikimedia.org/wiki/File:A_misty_day_in_nature_(32755531176).jpg |
| 5900491528.jpg | Public domain | https://commons.wikimedia.org/wiki/File:Cooper_High_School,_Robbinsdale_Yearbook_1972;_Talons_72_-_DPLA_-_b34e84216ac02d1f7871153bd97baa94_(page_68).jpg |
| 5914885504.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Detalle_de_techo.jpg |
| 5914916314.jpg | CC BY 3.0 | https://commons.wikimedia.org/wiki/File:Alvenaria_com_argamassa_polim%C3%A9rica.jpg |
| 5922872314.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Making_a_birthday_chair.jpg |
| 5933957922.jpg | Public domain | https://commons.wikimedia.org/wiki/File:BoarderX.JPG |
| 5949755544.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Bikepacking_through_Great_Divide_Basin,_Wyoming,_USA.jpg |
| 5986996457.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:A_tiny_leafhopper.jpg |
| 6017818854.jpg | CC0 | https://commons.wikimedia.org/wiki/File:Kevin_and_Bunny.jpg |
| 6025187394.jpg | CC BY-SA 3.0 | https://commons.wikimedia.org/wiki/File:California_Cut_In.jpg |
| 6030567370.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Guess_Who%3F_(39750112043).jpg |
| 6036113509.jpg | CC BY-SA 2.0 | https://commons.wikimedia.org/wiki/File:Make_me_happy_(24805200652).jpg |
| 6048604293.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:%D8%A7%D8%AC%D9%88%D8%A7%D8%A1_%D8%B1%D9%85%D8%B6%D8%A7%D9%86_%D9%85%D9%86_%D8%A7%D9%84%D9%85%D8%B3%D8%AC%D8%AF_%D8%A7%D9%84%D8%A7%D9%82%D8%B5%D9%89%D9%A2.jpg |
| 6096835713.jpg | No restrictions | https://commons.wikimedia.org/wiki/File:B.C.A._1911_No.2_on_plan_(9131787039).jpg |
| 6109541044.jpg | CC BY-SA 2.0 | https://commons.wikimedia.org/wiki/File:-i---i-_(5211216475).jpg |
| 6117406592.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:At_Salisbury_2023_016.jpg |
| 6233373580.jpg | CC BY-SA 3.0 | https://commons.wikimedia.org/wiki/File:Affresco_3_Carditello.jpg |
| 6286888384.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Ainstin_S_Dennis_NCLEX-RN_educator_portrait_5_2026.jpg |
| 6311911058.jpg | CC BY-SA 2.0 | https://commons.wikimedia.org/wiki/File:42-%C3%A5rs_kalas;-)_(5271166546).jpg |
| 6323629725.jpg | CC BY-SA 3.0 | https://commons.wikimedia.org/wiki/File:Cabines_de_t%C3%A9l%C3%A9ph%C3%A9rique_centre_commercial_Andorre.jpg |
| 6334223377.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Jeff_Lavin_.jpg |
| 6338465828.jpg | Public domain | https://commons.wikimedia.org/wiki/File:Floortjedejong.jpg |
| 6377546319.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Baby_enjoys_bottle_feeding_while_seated_in_a_cozy_chair_during_a_calm_afternoon_at_home.jpg |
| 6385329909.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Bathroom_stall_door_with_a_missing_handle.jpg |
| 6438389820.jpg | CC0 | https://commons.wikimedia.org/wiki/File:Architecture_patterns_at_night_(Unsplash).jpg |
| 6439253474.jpg | CC BY-SA 2.0 | https://commons.wikimedia.org/wiki/File:-i---i-_(50536253547).jpg |
| 6482334112.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:An_Oriental_whip_snake_with_its_tongue_flicking_out.jpg |
| 6484372979.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Harmony_of_the_Seas_VII.jpg |
| 6494264027.jpg | Public domain | https://commons.wikimedia.org/wiki/File:R%C3%B6mische_Kaiser._Augustus._a._Philae._Tempel_J,_Aeusssere_Nordwand;_b._Deb%C3%B4t_(D%C3%A2b%C3%BBd)._Erster_Raum._Westwand;_c-g._Kalabscheh_(Kal%C3%A2bishah)_(NYPL_b14291191-44092).jpg |
| 6496795113.jpg | Public domain | https://commons.wikimedia.org/wiki/File:18th_century_portrait_depicting_a_tawaif.jpg |
| 6501835205.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:%22%D0%94%D1%8B%D0%BC%D0%BA%D0%B0%22-_%D1%80%D1%83%D1%81%D1%81%D0%BA%D0%B8%D0%B9_%D0%BD%D0%B0%D1%80%D0%BE%D0%B4%D0%BD%D1%8B%D0%B9_%D1%82%D0%B0%D0%BD%D0%B5%D1%86.jpg |
| 6512337259.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Catss.jpg |
| 6522457962.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Mom_and_baby.jpg |
| 6534024751.jpg | CC BY-SA 3.0 | https://commons.wikimedia.org/wiki/File:500px_photo_(46018324).jpeg |
| 6550569741.jpg | CC BY-SA 3.0 | https://commons.wikimedia.org/wiki/File:500px_photo_(144733427).jpeg |
| 6575100303.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Bestlite_lamp_(8724495924)_(cropped).jpg |
| 6591224089.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Bake-ituna_Tratado_de_paz._Ibon_Aranberri._Makina_eskua_da._Argazkiak_Fotos_Akhonmedia_(33032713112).jpg |
| 6605954455.jpg | CC BY 3.0 | https://commons.wikimedia.org/wiki/File:Ano_novo_casa_nova_-_panoramio.jpg |
| 6637309450.jpg | Public domain | https://commons.wikimedia.org/wiki/File:Downhill_Skiing,_Lookout_Pass_(40749762032).jpg |
| 6693720131.jpg | CC BY-SA 2.0 | https://commons.wikimedia.org/wiki/File:A_misty_day_in_nature_(32672658871).jpg |
| 6704113546.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Mardi_Gras_in_the_French_Quarter_2005_-_Pram_and_Doorway.jpg |
| 6712897037.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:A_key_is_inserted_in_a_door_lock.jpg |
| 6726709536.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Ca_n%27Anneta.jpg |
| 6731447021.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:All_that_glitters..._-_Flickr_-_Stiller_Beobachter.jpg |
| 6732697383.jpg | Public domain | https://commons.wikimedia.org/wiki/File:Children_playing_with_mascote.jpg |
| 6734633438.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:3-%D0%94_%D0%9B%D0%B0%D0%B1%D0%BE%D1%80%D0%B0%D1%82%D0%BE%D1%80%D1%96%D1%8F_%D0%9A%D0%B2%D0%B0%D0%B4%D1%80%D0%B0%D1%82.jpg |
| 6837760137.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:20150201CAT_BA_MTB28.jpg |
| 6843088329.jpg | CC0 | https://commons.wikimedia.org/wiki/File:A_baby_playing_with_balls.jpg |
| 6846462744.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:BackcountryDownhill.JPG |
| 6850535098.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Beware_of_Cat_(14854865074).jpg |
| 6892144298.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Kathyrn_Beaumont_80th_Birthday_Party_at_Club33_(cropped).jpg |
| 6946633553.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:30894-Mei%C3%9Fen-1990-Vincenz_Richter_Mehrbildkarte-Br%C3%BCck_%26_Sohn_Kunstverlag.jpg |
| 6954726555.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Canbephihi.jpg |
| 6984602518.jpg | CC0 | https://commons.wikimedia.org/wiki/File:Bar_Restaurante_Sidrer%C3%ADa_Gran_V%C3%ADa_(25650975504).jpg |
| 7027236083.jpg | CC BY-SA 3.0 | https://commons.wikimedia.org/wiki/File:Aaron_Gwin_(USA).jpg |
| 7070995632.jpg | CC BY 3.0 | https://commons.wikimedia.org/wiki/File:500px_photo_(183485563).jpeg |
| 7099866376.jpg | CC BY-SA 3.0 | https://commons.wikimedia.org/wiki/File:500px_photo_(144733425).jpeg |
| 7148906330.jpg | CC BY-SA 2.0 | https://commons.wikimedia.org/wiki/File:Bangladesh_DSC_0523_(3931027652).jpg |
| 7152178256.jpg | CC BY 3.0 | https://commons.wikimedia.org/wiki/File:-_panoramio_(3667).jpg |
| 7153944009.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:A_photo_called_P1380087.jpg |
| 7190662481.jpg | CC BY 3.0 | https://commons.wikimedia.org/wiki/File:Kids_Night_(166369455).jpeg |
| 7201801328.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Castle_man_cave_panorama_(39081901042).jpg |
| 7202593856.jpg | CC BY-SA 2.0 | https://commons.wikimedia.org/wiki/File:A_misty_day_in_nature_(32642619432).jpg |
| 7205282903.jpg | CC BY 3.0 | https://commons.wikimedia.org/wiki/File:Exterior_shot_of_Roast_restaurant.JPG |
| 7213918744.jpg | Public domain | https://commons.wikimedia.org/wiki/File:DSM_modelling.jpg |
| 7226626281.jpg | CC BY-SA 3.0 | https://commons.wikimedia.org/wiki/File:Banio_en_reformas.jpeg |
| 7236124634.jpg | CC0 | https://commons.wikimedia.org/wiki/File:Hans_Eiskonen_2015_(Unsplash).jpg |
| 7244167969.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:A_cheerful_child_is_splashing_in_a_pool_while_sitting_on_a_bright_pink_flamingo_float.jpg |
| 7275949467.jpg | CC BY-SA 3.0 | https://commons.wikimedia.org/wiki/File:Birthday_decoration.jpg |
| 7276006279.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Alex_ceiling.jpg |
| 7310186092.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Br%C3%BCckkanal_Biergarten.jpg |
| 7324065266.jpg | CC BY-SA 3.0 | https://commons.wikimedia.org/wiki/File:COLLECTIE_TROPENMUSEUM_Baboes_en_kinderen_tijdens_de_viering_van_de_eerste_verjaardag_van_Beppie_Landzaad_Pematangsiantar_TMnr_60021763.jpg |
| 7369900520.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Andrew-At-KAPX-WFO.jpg |
| 7370812628.jpg | CC BY-SA 3.0 | https://commons.wikimedia.org/wiki/File:Betonepox_ob%C3%BDvac%C3%AD_pokoj.JPG |
| 7448962147.jpg | CC BY 3.0 | https://commons.wikimedia.org/wiki/File:500px_photo_(239840831).jpeg |
| 7456031363.jpg | Public domain | https://commons.wikimedia.org/wiki/File:%22At_Night%22.jpg |
| 7456773332.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Dirts_found_in_milky_doughnut_%F0%9F%8D%A9.jpg |
| 7491594301.jpg | CC BY-SA 3.0 | https://commons.wikimedia.org/wiki/File:Dietenheim_Museum_Bauernstube_1100.jpg |
| 7499285077.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:A_person_holds_a_glass_bowl_filled_with_water.jpg |
| 7508277996.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:%D0%9C%D0%BE%D1%80%D0%BE%D0%B7%D0%BD%D0%B8%D0%B9_%D1%80%D0%B0%D0%BD%D0%BE%D0%BA_%D0%BD%D0%B0%D0%B4_%D0%AF%D1%80%D0%B5%D0%BC%D1%87%D0%B5%D1%8E.jpg |
| 7524616168.jpg | Public domain | https://commons.wikimedia.org/wiki/File:BethAm.jpg |
| 7526714995.jpg | CC BY-SA 3.0 | https://commons.wikimedia.org/wiki/File:Mahnwache_Netzzensur_2009_14.JPG |
| 7527833067.jpg | CC BY-SA 2.0 | https://commons.wikimedia.org/wiki/File:20120522-DSC00434-2_(7330346600).jpg |
| 7545369813.jpg | CC BY-SA 3.0 | https://commons.wikimedia.org/wiki/File:Chalet_restaurant_du_Plan.jpg |
| 7550569930.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Belle_chambre.jpg |
| 7569929635.jpg | Public domain | https://commons.wikimedia.org/wiki/File:1946-07-01_Hotel_Edison_Green_Room_bar,_ball_room,_dining_room,_chamber_A.jpg |
| 7587042661.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Caf%C3%A9_Paradiso.jpg |
| 7596100722.jpg | CC BY-SA 3.0 | https://commons.wikimedia.org/wiki/File:EcoCute.jpg |
| 7601518784.jpg | Public domain | https://commons.wikimedia.org/wiki/File:Garnier-Tony,_Lyon,_stade_nautique.jpg |
| 7605258089.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:How_we_celebrate_our_birthdays_parties.jpg |
| 7622499210.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:%D0%9F%D1%91%D1%82%D1%80_%D0%A0%D0%B5%D1%82%D0%B2%D0%B8%D1%86%D0%BA%D0%B8%D0%B9_%D1%81_%D0%B2%D0%BD%D1%83%D0%BA%D0%BE%D0%BC_1987.jpg |
| 7633004670.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Bibio_porte.jpg |
| 7688937687.jpg | Public domain | https://commons.wikimedia.org/wiki/File:Children_at_play_in_a_no-till_field_(54155406186).jpg |
| 7726792031.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:-i---i-_(2207698823).jpg |
| 7729240521.jpg | CC BY-SA 2.0 | https://commons.wikimedia.org/wiki/File:A_misty_day_in_nature_(32415482890).jpg |
| 7729750815.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:A_cozy_kitchen_is_filled_with_holiday_decorations.jpg |
| 7730797888.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Autor_propio.jpg |
| 7780417396.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Barinterno.jpg |
| 7787451772.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Chef_prepares_fresh_ingredients_by_chopping_red_vegetables.jpg |
| 7812759843.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Beside_the_St._Paul%27s_ruins.jpg |
| 7823939582.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Children_playing_cards.jpg |
| 7875729532.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Celebration_of_a_child%27s_birthday_with_guests_and_cake_in_a_lively_indoor_setting.jpg |
| 7881669704.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Bucuresti,_Romania._Pregatiri_de_Craciun._5_decembrie_2022._(3).jpg |
| 7886186758.jpg | Public domain | https://commons.wikimedia.org/wiki/File:Neues_Reich._Dynastie_XXVI._Pyramiden_von_Saq%C3%A2ra_(Saqq%C3%A2rah)._Grab_24,_Raum_B-_a._b._S%C3%BCdwand;_c._Westwand_(NYPL_b14291191-38441).jpg |
| 7906828567.jpg | CC BY-SA 2.0 | https://commons.wikimedia.org/wiki/File:Bell_Rope_(5354315338).jpg |
| 7917272539.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:24_hour_mountain_bike_races_(102237778).jpg |
| 7930446554.jpg | CC BY 3.0 | https://commons.wikimedia.org/wiki/File:Different-ski-styles.jpg |
| 7931699150.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:At_Tenerife_2022_480.jpg |
| 7945590220.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Blat_kuchenny_o%C5%9Bwietlony_ta%C5%9Bm%C4%85_LED_3000K.jpg |
| 7964013849.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Heat_Relief!.jpg |
| 7978693786.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Collection_of_essential_cooking_tools_hanging_on_a_rustic_wall.jpg |
| 8007242890.jpg | CC0 | https://commons.wikimedia.org/wiki/File:Adriana_Retyte_Portrait.jpg |
| 8031289124.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:9_%D1%84%D0%BE%D1%82%D0%BE_%D0%94%D0%B2%D0%B5%D1%80%D1%8C_%D0%B2_%D0%BA%D0%B0%D0%B1%D0%B8%D0%BD%D1%83_%D0%BC%D0%B0%D1%88%D0%B8%D0%BD%D0%B8%D1%81%D1%82%D0%B0.jpg |
| 8039134167.jpg | CC0 | https://commons.wikimedia.org/wiki/File:Architecture_(19341830430).jpg |
| 8043159024.jpg | CC0 | https://commons.wikimedia.org/wiki/File:20190617_Nebbia_(1).jpg |
| 8050616901.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Ada_Lovelace_200th_Birthday_Party.jpg |
| 8088696056.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Bokeh_Weihnachtsstern.jpg |
| 8130456941.jpg | CC BY 4.0 | https://commons.wikimedia.org/wiki/File:Abdiev_Almanbet_portrait.jpg |
| 8131707688.jpg | CC0 | https://commons.wikimedia.org/wiki/File:Beveled_indented_top_edge_grey_speckled_spotted_discolored_travertine_texture.jpg |
| 8132552525.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Adele_Raemer_self-portrait.jpg |
| 8178016821.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Algiers_bay_lightened_by_moon_light.jpg |
| 8215890394.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:20150801_xl_P1010109_Wurm_auf_Bergstrasse_nach_Gerstruben.JPG |
| 8238065031.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Cory_Allen_at_The_Ivy,_Los_Angeles_(June_2010).jpg |
| 8255334151.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:A_Real_Christmas_Tree,_Con_Thien,_Vietnam,_1968_(11516145555).jpg |
| 8257532204.jpg | Attribution | https://commons.wikimedia.org/wiki/File:Elatohori_ski_center.jpg |
| 8268792529.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:20170907_181858jpg.0.jpg |
| 8282742122.jpg | CC BY-SA 3.0 | https://commons.wikimedia.org/wiki/File:Fernandodelavega.jpg |
| 8289911536.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Certaldo_Alto_Ca_Messer_Boccaccio_Wirtshausschild.jpg |
| 8360998621.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:2018-02-13_(622)_Overgrown_wall_at_Bahnhof_Mauthausen.jpg |
| 8403006590.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:ElConventoGeneral.jpg |
| 8447063322.jpg | CC BY-SA 2.0 | https://commons.wikimedia.org/wiki/File:6_bis--5-1-2014-Charca-con-niebla-Web-m%C3%ADa_en_casa_de_Amador_(21421052565).jpg |
| 8453698740.jpg | CC BY 3.0 | https://commons.wikimedia.org/wiki/File:Bridal_Mehndi_Design.jpg |
| 8472833978.jpg | Public domain | https://commons.wikimedia.org/wiki/File:Assignment-_48-DPA-K_Modernization)_Building_modernization_(work_around_Main_Interior)_(48-DPA-K_Modernization_DSC_0132.JPG_-_DPLA_-_579cfed350184744d365da19d3b4c4f6.JPG |
| 8509126919.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Back_view_of_a_kid_blowing_candles_at_birthday_party.jpg |
| 8555942312.jpg | CC BY 4.0 | https://commons.wikimedia.org/wiki/File:Amir_Parvin_Hosseini_2023.jpg |
| 8563607568.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Costa_Rica_-_San_Jos%C3%A9_25.JPG |
| 8565883998.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:A_young_child_stands_in_shallow_water,_enjoying_the_coolness_of_the_pool_while_wearing_a_colorful_swimsuit._The_sunlight_reflects_off_the_water,_creating_a_joyful_atmosphere.jpg |
| 8573876439.jpg | CC0 | https://commons.wikimedia.org/wiki/File:35mm_Film_Self_portrait_of_Preston_Hazard.jpg |
| 8574068346.jpg | Public domain | https://commons.wikimedia.org/wiki/File:R%C3%B6mische_Kaiser._Augustus._Dendera_(Dandara)._Grosser_Tempel-_a._S%C3%A4ulenhalle;_b-e._Aussenseite;_(b.c.)_Hinterwand;_(d.)_Ostwand;_(e.)Westwand_(NYPL_b14291191-44089).jpg |
| 8579430469.jpg | CC BY 4.0 | https://commons.wikimedia.org/wiki/File:Arara_caninde_Ara_ararauna_bokeh.jpg |
| 8582384186.jpg | Public domain | https://commons.wikimedia.org/wiki/File:AS_ski.jpg |
| 8584229645.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Art_11.jpg |
| 8590508800.jpg | CC0 | https://commons.wikimedia.org/wiki/File:2006_August_26_Metal_festival_in_Uppsala.jpg |
| 8592391658.jpg | Public domain | https://commons.wikimedia.org/wiki/File:Ada_(6893514233).jpg |
| 8604213241.jpg | CC0 | https://commons.wikimedia.org/wiki/File:2025-03-12_Castel_Nuovo_Entrance_Door_Right.jpg |
| 8636757230.jpg | CC BY-SA 3.0 | https://commons.wikimedia.org/wiki/File:Dol.jpg |
| 8658337737.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:%22%D0%94%D1%8B%D0%BC%D0%BA%D0%B0%22-%D1%81%D0%BA%D0%BE%D0%BC%D0%BE%D1%80%D0%BE%D1%85%D0%B8_%D0%B2_%D1%82%D0%B0%D0%BD%D1%86%D0%B5.jpg |
| 8660803253.jpg | CC BY 3.0 | https://commons.wikimedia.org/wiki/File:Christbaum_in_der_Mauer.JPG |
| 8671140588.jpg | CC BY-SA 2.0 | https://commons.wikimedia.org/wiki/File:Bedroom_in_the_Bosniak_house.jpg |
| 8691403367.jpg | CC BY 3.0 | https://commons.wikimedia.org/wiki/File:500px_photo_(44828792).jpeg |
| 8727480349.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Cat_waking_up_from_a_nap.jpg |
| 8736273959.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Happy_birthday_shosh.jpg |
| 8788843050.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Abdelkader_Medjaoui.jpg |
| 8796465342.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Fale%C5%A1n%C3%BD_baz%C3%A9n,_Techmania,_Plze%C5%88.jpg |
| 8866391315.jpg | CC BY-SA 3.0 | https://commons.wikimedia.org/wiki/File:Fontaine_Place_des_Festivals_34.jpg |
| 8869292685.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Backsteinmauer_mit_grauen_Rillen.JPG |
| 8870956164.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Extreme_snowpark_at_the_%22SOK%22_ski_resort.jpg |
| 8871756531.jpg | CC BY-SA 3.0 | https://commons.wikimedia.org/wiki/File:Carnuntum_Haus_des_Lucius_-_Wohnzimmer_2.jpg |
| 8891126330.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Children_at_play_with_a_toy_car.jpg |
| 8901590497.jpg | CC0 | https://commons.wikimedia.org/wiki/File:Arbol_de_los_Sue%C3%B1os_(42218315504).jpg |
| 8951718033.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Blower_Door_Test.jpg |
| 9012620998.jpg | CC BY 3.0 | https://commons.wikimedia.org/wiki/File:500px_photo_(68126493).jpeg |
| 9038941178.jpg | Public domain | https://commons.wikimedia.org/wiki/File:Akiva_Eger_CROPPED_1.jpg |
| 9052420343.jpg | GFDL | https://commons.wikimedia.org/wiki/File:Gory.jpg |
| 9067197461.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Laurie%27s_4th_Birthday_4_(5275790904).jpg |
| 9070763318.jpg | CC0 | https://commons.wikimedia.org/wiki/File:Ancient_walls_in_Durr%C3%ABs.jpg |
| 9092894393.jpg | Public domain | https://commons.wikimedia.org/wiki/File:A_Sixteenth_Century_Room.jpg |
| 9133074649.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Mummy_Label_from_the_Roman_Period,_(30_BCE-_395_CE,_Possibly_from_Thebes,_Brighton_Museum.jpg |
| 9134145006.jpg | CC BY-SA 2.0 | https://commons.wikimedia.org/wiki/File:Abstract_bokeh_lights_(22142580635).jpg |
| 9157383236.jpg | CC BY 4.0 | https://commons.wikimedia.org/wiki/File:A_barn_swallow_collect_mud_DSC_7668_copy.jpg |
| 9172365592.jpg | CC BY-SA 3.0 | https://commons.wikimedia.org/wiki/File:Ceiling_3_(138191859).jpeg |
| 9196678862.jpg | CC BY-SA 3.0 | https://commons.wikimedia.org/wiki/File:-_panoramio_(2619).jpg |
| 9238605555.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Birthdayamritfood.jpg |
| 9271809938.jpg | CC0 | https://commons.wikimedia.org/wiki/File:Bedroom_window_(Unsplash).jpg |
| 9338763385.jpg | Public domain | https://commons.wikimedia.org/wiki/File:Pele_2007.jpg |
| 9355889331.jpg | CC BY-SA 3.0 | https://commons.wikimedia.org/wiki/File:A_Few_Drops_(141048319).jpeg |
| 9420904002.jpg | CC BY-SA 3.0 de | https://commons.wikimedia.org/wiki/File:Bundesarchiv_Bild_183-1993-0105-514,_Wolfgang_Harich_in_seiner_Wohnung.jpg |
| 9424656020.jpg | CC0 | https://commons.wikimedia.org/wiki/File:A_pic_of_cat.jpg |
| 9434483211.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Ainstin_S_Dennis_NCLEX-RN_educator_portrait_4_2026.jpg |
| 9440748916.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Bethlehem514.jpg |
| 9441394359.jpg | Public domain | https://commons.wikimedia.org/wiki/File:Antesala.jpg |
| 9487601377.jpg | CC BY-SA 3.0 | https://commons.wikimedia.org/wiki/File:Ceiling-and-windows-in-an-attic-apartment.jpg |
| 9493701716.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Apurva_kher.jpg |
| 9506382055.jpg | Public domain | https://commons.wikimedia.org/wiki/File:Bigfoots.jpg |
| 9526395881.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Container_storage_at_a_kitchen_pantry_with_different_types_of_food_items_in_jars_and_bottles_at_home.jpg |
| 9544623141.jpg | Public domain | https://commons.wikimedia.org/wiki/File:04_Malcolm_counsels_the_townspeople_of_Mansfield_to_resistance-Illust_by_Johan_Schonberg_for_Lion_of_the_North_by_G_A_Henty.jpg |
| 9549338682.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Lunch_at_Clover_Grill.jpg |
| 9600729341.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Arme_Mela....._(48543173502).jpg |
| 9606729652.jpg | CC BY 2.0 | https://commons.wikimedia.org/wiki/File:Abstarct_Christmas_Tree.jpg |
| 9612492683.jpg | CC0 | https://commons.wikimedia.org/wiki/File:Beige_tan_sand_faced_finish_clean_seamless_building_wall_texture.jpg |
| 9630531985.jpg | Public domain | https://commons.wikimedia.org/wiki/File:Bike_Park_Bottom.JPG |
| 9634005149.jpg | CC BY 4.0 | https://commons.wikimedia.org/wiki/File:Armenian_Church_of_St_Philip_14.jpg |
| 9641331834.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:2_Ustad_Sabir_Khan_pic_1.jpg |
| 9673809682.jpg | CC BY-SA 3.0 | https://commons.wikimedia.org/wiki/File:Bedroom_large_double_bed.jpg |
| 9677921126.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Alton_Towers_Lightopia_2023_006.jpg |
| 9687564004.jpg | Public domain | https://commons.wikimedia.org/wiki/File:170602-G-XX000-104.jpg |
| 9719055015.jpg | CC BY-SA 2.0 | https://commons.wikimedia.org/wiki/File:Hand-2_(3641376458).jpg |
| 9719300375.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Magbere_3.jpg |
| 9722054693.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:2026-05-25-Ringeltaube_vor_dem_K%C3%B6lner_Dom-068873.jpg |
| 9851038731.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:2019-08-28-YANGSU.jpg |
| 9892095844.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Draganovhouse1.jpg |
| 9896805295.jpg | Public domain | https://commons.wikimedia.org/wiki/File:272-foto-de-snowboard.jpg |
| 9901733916.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:20150201CAT_BA_MTB5.jpg |
| 9916974668.jpg | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Fraidy-Cat-Promotional-Cel.jpg |
| 9926908053.jpg | CC BY 3.0 | https://commons.wikimedia.org/wiki/File:Goofy_-_20th_Leysin_Nescaf%C3%A9_Champs,_8th_-_13th_February_2011_(1).jpg |
| 9942166224.jpg | CC0 | https://commons.wikimedia.org/wiki/File:Eric_Bob_Bobrowicz_on_a_photo_shooting_day_in_Serre_Chevalier.jpg |
| 9994247219.jpg | CC0 | https://commons.wikimedia.org/wiki/File:Beaulieu_Christmas_Trees_(Unsplash).jpg |
| 9999769984.jpg | CC0 | https://commons.wikimedia.org/wiki/File:Baby_holding_adult_hand.jpg |

Source: the CC-licensed Wikimedia Commons pull `scripts/triage_heads/public_corpus.py` produces; licenses and attribution pages are recorded above. Images are not redistributed with this bundle; the repository's license applies to the training and serving code.

This head is shipped as a rank-only warning (`OBSTRUCTED (edge)`): a flagged picture loses to a clean sibling of the same moment and is never dropped on its own. See `docs-site/docs/how-it-chooses/` and `src/immich_memories/analysis/editorial_obstruction.py`.
