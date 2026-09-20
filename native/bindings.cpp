//
// pybind11 bindings for the ReachVariantEditor engine (the non-UI code that reads/writes
// Halo: Reach game variant files and compiles/decompiles Megalo script). This intentionally
// bypasses ReachEditorState (the GUI's singleton) and works with GameVariant objects
// directly, so multiple variants can be open at once and there's no hidden global state.
//
// Scope (v1): full read/write access to custom game options (general/respawn/social/map/
// team/loadouts), teams, player traits, loadout palettes, map permissions, player rating
// params, and Title Update 1 options, plus load/save and Megalo script compile/decompile
// via source text (matching how the tool's own headless CLI works). Also bound: script-defined
// options/traits/widgets/forge labels/stats, Firefight (including per-round wave/squad
// configuration, custom skulls, and the bonus wave), and a friendly object-type name lookup.
// Also now bound: the real Megalo Trigger/Opcode/Condition/Action/OpcodeArgValue object graph
// (game_variants/components/megalo/{trigger,opcode,opcode_arg,code_block,conditions,actions,
// opcode_arg_types/**}.*) -- see MultiplayerData.trigger()/trigger_count and AST.md's "engine
// AST" section. Structured (non-text) fields for ~40 concrete OpcodeArgValue subclasses --
// constants, indices, enums, flags, icons, forge-label/player-traits/widget references,
// shapes/vectors/player-sets/meter-parameters/paired-variables -- not just the common Variable
// base and its own 5 leaf classes. Mutation of already-loaded opcodes' fields (Condition.
// inverted/or_group/action, Variable.which/index, every new scalar/enum/flag argument field
// above) is read/write and does persist through .save() -- confirmed directly, not assumed (see
// AST.md's "Two-way mutation" section). Also now supports real CONSTRUCTION of brand-new opcodes
// (Condition()/Action() + .function + add_argument(OpcodeArgTypeinfo.create()/OpcodeArgValue.
// clone()), CodeBlock.add_opcode()) -- an earlier pass wrongly assumed this needed driving
// GameVariantDataMultiplayer's raw struct-of-arrays serialization manually; confirmed by testing
// (not just reading) that GameVariant.save() already does this itself on every save
// (generate_flat_opcode_lists(), called unconditionally from GameVariantDataMultiplayer::write()),
// so a plain CodeBlock.opcodes append is genuinely sufficient -- see AST.md's "Constructing new
// opcodes" section for the full workflow, including the one thing that IS the caller's own
// responsibility (a new Condition's own .or_group). This needed py::smart_holder on the whole
// Opcode/OpcodeArgValue hierarchies (pybind11 v3's holder for safe Python<->C++ ownership transfer
// via std::unique_ptr parameters/returns -- the previous, simpler holder only supported one
// direction). Also bound: OpcodeArgValueFormatString(Persistent) (the "%s"/"%n" format-string
// mechanism -- OpcodeStringToken's own OpcodeArgValue* sub-argument uses the same unique_ptr
// ownership-transfer pattern as Opcode.add_argument()) and OpcodeArgValueMegaloScope (embeds a
// second CodeBlock by value -- the "Run Inline Trigger" argument, whose own .data reuses
// CodeBlock's existing opcode(i)/opcode_count/add_opcode() outright). Also bound: constructing a
// whole new Trigger (MultiplayerData.add_trigger(), which cobb::indexed_list already
// constructs/owns via emplace_back() -- no unique_ptr transfer needed there at all) and wiring one
// as event-bound (bind_trigger_as_event(), keeping Trigger.entry_type and the engine's separate
// TriggerEntryPoints lookup table in sync atomically -- confirmed both need to agree by compiling
// a real "on pregame: ..." block and inspecting both). Roadmap item 3 (README.md) is now
// essentially complete at the binding level; see AST.md's "engine AST" section for the full
// writeup and its still-open, deliberately-separate follow-ons (per-argument-type Python pydantic
// wrapping in mide.megalo_ast.engine, and reconstructing a nested if/for-each tree from the flat
// opcode graph -- mide/megalo_ast's text layer already covers that need a different way).
//
#include <memory>

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include "type_casters.h"

#include <QFile>
#include <QSaveFile>
#include <QDataStream>

#include "game_variants/base.h"
#include "game_variants/io_process.h"
#include "game_variants/warnings.h"
#include "game_variants/types/multiplayer.h"
#include "game_variants/components/custom_game_options.h"
#include "game_variants/components/teams.h"
#include "game_variants/components/player_traits.h"
#include "game_variants/components/loadouts.h"
#include "game_variants/components/powerups.h"
#include "game_variants/components/map_permissions.h"
#include "game_variants/components/player_rating_params.h"
#include "game_variants/components/tu1_options.h"
#include "formats/content_author.h"
#include "formats/ugc_header.h"
#include "game_variants/types/firefight.h"
#include "game_variants/components/firefight_wave_traits.h"
#include "game_variants/components/firefight_round.h"
#include "game_variants/components/firefight_custom_skull.h"
#include "game_variants/data/object_types.h"
#include "game_variants/components/megalo/compiler/compiler.h"
#include "game_variants/components/megalo/decompiler/decompiler.h"
#include "game_variants/components/megalo/trigger.h"
// Pulls in every opcode_arg_types/*.h -- constants/enums/flags/indices, the variables/ family,
// fireteam_list/forge_label/format_string/icons/incident/object_type/player_set/player_traits/
// shape/sound/specific_variable/timer_rate/variant_string_id/vector3/waypoint_icon/widget_related,
// and megalo_scope (MCC's inline-trigger extension) -- see AST.md's "engine AST" section for which
// of these are actually bound below (most; format_string/megalo_scope deliberately not yet, see
// the comment above their would-be section).
#include "game_variants/components/megalo/opcode_arg_types/all.h"
#include "formats/localized_string_table.h"
#include "game_variants/components/megalo/forge_label.h"
#include "game_variants/components/megalo/widgets.h"
#include "game_variants/components/megalo_options.h"
#include "game_variants/components/megalo_game_stats.h"
#include "formats/bitset.h"

namespace py = pybind11;

namespace {

   // ---- load / save --------------------------------------------------------------------

   std::unique_ptr<GameVariant> load_variant(const std::string& path) {
      QString q_path = QString::fromUtf8(path.c_str());
      QFile   file(q_path);
      if (!file.open(QIODevice::ReadOnly))
         throw std::runtime_error("Failed to open file: " + file.errorString().toStdString());
      auto buffer = file.readAll();

      auto variant = std::make_unique<GameVariant>();
      bool success = q_path.endsWith(".mglo", Qt::CaseInsensitive)
         ? variant->read_mglo(buffer.data(), buffer.size())
         : variant->read(buffer.data(), buffer.size());
      if (!success)
         throw std::runtime_error("Failed to parse game variant (not a valid/recognized file).");
      return variant;
   }

   std::vector<std::string> take_load_warnings() {
      auto& log = GameEngineVariantLoadWarningLog::get();
      std::vector<std::string> out;
      out.reserve(log.warnings.size());
      for (auto& w : log.warnings)
         out.push_back(w.toStdString());
      log.warnings.clear();
      return out;
   }

   void save_variant(GameVariant& variant, const std::string& path) {
      QString out_path = QString::fromUtf8(path.c_str());

      QSaveFile file(out_path);
      if (!file.open(QIODevice::WriteOnly))
         throw std::runtime_error("Unable to open destination file for writing: " + file.errorString().toStdString());

      GameVariantSaveProcess save_process;
      if (out_path.endsWith(".mglo", Qt::CaseInsensitive))
         save_process.set_flag(GameVariantSaveProcess::flag::save_bare_mglo);

      variant.write(save_process);
      if (save_process.variant_is_editor_only()) {
         file.cancelWriting();
         throw std::runtime_error("The updated game variant exceeds Reach's file format limits and cannot be saved as a playable file.");
      }

      QDataStream out(&file);
      out.setVersion(QDataStream::Qt_4_5);
      out.writeRawData((const char*)save_process.writer.bytes.data(), save_process.writer.bytes.get_bytespan());
      file.commit();
   }

   std::string decompile_variant(GameVariant& variant) {
      Megalo::Decompiler decompiler(variant);
      decompiler.decompile();
      return decompiler.current_content.toStdString();
   }

   // ---- Megalo compile -------------------------------------------------------------------

   struct CompileMessage {
      int line = 0;
      int col = 0;
      std::string text;
   };

   struct CompileResult {
      bool success = false;
      std::vector<CompileMessage> fatal_errors;
      std::vector<CompileMessage> errors;
      std::vector<CompileMessage> warnings;
      std::vector<CompileMessage> notices;
   };

   std::vector<CompileMessage> to_messages(const Megalo::Compiler::log_t& log) {
      std::vector<CompileMessage> out;
      out.reserve(log.size());
      for (auto& item : log)
         out.push_back(CompileMessage{ item.pos.line, item.pos.col(), item.text.toStdString() });
      return out;
   }

   CompileResult compile_script(GameVariantDataMultiplayer& mp, const std::string& source, bool create_unresolved_strings) {
      Megalo::Compiler compiler(mp);
      compiler.parse(QString::fromUtf8(source.c_str()));

      CompileResult result;
      result.fatal_errors = to_messages(compiler.get_fatal_errors());
      result.errors       = to_messages(compiler.get_non_fatal_errors());
      result.warnings      = to_messages(compiler.get_warnings());
      result.notices       = to_messages(compiler.get_notices());

      if (compiler.has_errors()) {
         result.success = false;
         return result;
      }

      if (create_unresolved_strings) {
         auto& list = compiler.get_unresolved_string_references();
         if (!list.empty()) {
            for (auto& item : list)
               item.pending.action = Megalo::Compiler::unresolved_string_pending_action::create;
            compiler.handle_unresolved_string_references();
         }
      }

      compiler.apply();
      result.success = true;
      return result;
   }

   // ---- array-field accessors (kept out of def_readwrite to avoid stl.h's by-value copy
   //      semantics on std::array, which would break in-place mutation from Python) --------

   template <typename Array>
   auto& index_into(Array& arr, size_t i) {
      if (i >= arr.size())
         throw py::index_error(std::to_string(i));
      return arr[i];
   }

   template <typename Bitset>
   std::vector<int> set_bit_indices(const Bitset& b) {
      std::vector<int> result;
      for (int i = 0; i < Bitset::flag_count; i++)
         if (b.bits.test(i))
            result.push_back(i);
      return result;
   }

   // Reverse of set_bit_indices() above -- replaces a bitset's entire contents with exactly the
   // given indices (clear, then set each one). Used for the option-visibility toggle lists and
   // used_object_type_indices, which were read-only (set_bit_indices() with no counterpart) until
   // mide.settings_writer grew a write path for OptionVisibility/RequiredObjectTypes.
   template <typename Bitset>
   void set_bit_indices_from(Bitset& b, const std::vector<int>& indices) {
      b.bits.clear();
      for (int i : indices) {
         if (i < 0 || i >= Bitset::flag_count)
            throw py::index_error(std::to_string(i));
         b.bits.set(i);
      }
   }

   // ---- object type friendly names (Megalo::enums::object_type, formats/detailed_enum.h) -----

   size_t object_type_count() {
      return Megalo::enums::object_type.size();
   }

   std::string object_type_name(uint32_t index) {
      auto* def = Megalo::enums::object_type.item(index);
      if (!def)
         throw py::index_error(std::to_string(index));
      auto name = def->get_friendly_name();
      if (name.isEmpty())
         name = QString::fromLatin1(def->name.c_str()); // same fallback as ui/widgets/mp_object_type_combobox.h
      return name.toStdString();
   }

   // ---- size/usage stats (space usage + trigger/condition/action counts, mirroring
   //      ui/script_editor/bottom_bar.cpp's own two-step update sequence) --------------------

   ReachMPSizeData get_full_size_data(GameVariantDataMultiplayer& mp) {
      ReachMPSizeData data;
      data.update_from(mp);
      data.update_script_from(mp); // fills in bits.script_content and counts.{triggers,conditions,actions} -- get_size_data() alone (C++-only today) skips this
      return data;
   }

} // namespace

PYBIND11_MODULE(_reachvarianttool, m) {
   m.doc() = "Bindings for the ReachVariantEditor engine: load/edit/save Halo: Reach game variants.";

   // ---- top-level load/save/compile/decompile -----------------------------------------

   m.def("load", &load_variant, py::arg("path"),
      "Load a game variant (.bin) or bare Megalo script (.mglo) from disk.");
   m.def("take_load_warnings", &take_load_warnings,
      "Return and clear the warnings produced by the most recent load() call.");

   py::class_<CompileMessage>(m, "CompileMessage")
      .def_readonly("line", &CompileMessage::line)
      .def_readonly("col", &CompileMessage::col)
      .def_readonly("text", &CompileMessage::text)
      .def("__repr__", [](const CompileMessage& s) {
         return "<CompileMessage line=" + std::to_string(s.line) + " col=" + std::to_string(s.col) + " " + s.text + ">";
      });

   py::class_<CompileResult>(m, "CompileResult")
      .def_readonly("success", &CompileResult::success)
      .def_readonly("fatal_errors", &CompileResult::fatal_errors)
      .def_readonly("errors", &CompileResult::errors)
      .def_readonly("warnings", &CompileResult::warnings)
      .def_readonly("notices", &CompileResult::notices)
      .def("__bool__", [](const CompileResult& s) { return s.success; });

   // ---- string table (used for team names, etc.) ----------------------------------------

   py::enum_<reach::language>(m, "Language")
      .value("english", reach::language::english)
      .value("japanese", reach::language::japanese)
      .value("german", reach::language::german)
      .value("french", reach::language::french)
      .value("spanish", reach::language::spanish)
      .value("mexican", reach::language::mexican)
      .value("italian", reach::language::italian)
      .value("korean", reach::language::korean)
      .value("chinese_traditional", reach::language::chinese_traditional)
      .value("chinese_simplified", reach::language::chinese_simplified)
      .value("portugese", reach::language::portugese)
      .value("polish", reach::language::polish);

   py::class_<ReachString>(m, "ReachString")
      .def("get_content", [](ReachString& s, reach::language l) { return s.get_content(l); })
      .def("has_content", [](ReachString& s, reach::language l) { return s.has_content(l); },
         "Whether this language was actually saved -- distinct from get_content() being empty, "
         "which is also what an unsaved language looks like.")
      .def("set_content", [](ReachString& s, reach::language l, const std::string& text) { s.set_content(l, text); })
      .def_property("text",
         [](ReachString& s) { return s.get_content(reach::language::english); },
         [](ReachString& s, const std::string& text) { s.set_content(reach::language::english, text); },
         "Convenience accessor for the English-language string.")
      .def("empty", &ReachString::empty);

   py::class_<ReachStringTable>(m, "ReachStringTable")
      .def("__len__", &ReachStringTable::size)
      .def("__getitem__", [](ReachStringTable& t, size_t i) -> ReachString& {
         auto* entry = t.get_entry(i);
         if (!entry)
            throw py::index_error(std::to_string(i));
         return *entry;
      }, py::return_value_policy::reference_internal)
      .def("add_new", &ReachStringTable::add_new, py::return_value_policy::reference_internal)
      .def_property_readonly("capacity", &ReachStringTable::capacity)
      .def("get_size_to_save", &ReachStringTable::get_size_to_save,
         "Bytes this table would take up if saved right now -- compare against max_buffer_size "
         "to check whether recently-written content still fits.")
      .def_readonly("max_buffer_size", &ReachStringTable::max_buffer_size);

   // ---- teams -----------------------------------------------------------------------------

   py::class_<ReachTeamData>(m, "TeamData")
      .def_readwrite("flags", &ReachTeamData::flags)
      .def_readwrite("initial_designator", &ReachTeamData::initialDesignator)
      .def_readwrite("spartan_or_elite", &ReachTeamData::spartanOrElite)
      .def_readwrite("color_primary", &ReachTeamData::colorPrimary)
      .def_readwrite("color_secondary", &ReachTeamData::colorSecondary)
      .def_readwrite("color_text", &ReachTeamData::colorText)
      .def_readwrite("fireteam_count", &ReachTeamData::fireteamCount)
      .def("get_name", &ReachTeamData::get_name, py::return_value_policy::reference_internal)
      .def_property("name",
         [](ReachTeamData& t) -> py::object {
            auto* name = t.get_name();
            if (!name) return py::none();
            return py::cast(name->get_content(reach::language::english));
         },
         [](ReachTeamData& t, const std::string& text) {
            auto* name = t.get_name();
            if (!name) name = t.name.add_new(); // team name table starts out empty; create its one entry on first write
            if (name) name->set_content(reach::language::english, text);
         });

   // ---- player traits (defense/offense/movement/appearance/sensors) -----------------------
   //
   // The enums below are registered so trait/loadout fields can round-trip as readable names.
   // NOTE: fields of these enum types are stored as cobb::bitnumber<N, reach::X> (see
   // player_traits.h / loadouts.h), so type_casters.h's generic bitnumber caster still wins over
   // these py::enum_ registrations and hands Python a plain int -- reconstruct explicitly in
   // Python (e.g. `Weapon(raw_int).name`) to get the name back. See app/yaml_export.py's
   // _enum_name() helper.

   py::enum_<reach::damage_resist>(m, "DamageResist")
      .value("unchanged", reach::damage_resist::unchanged)
      .value("value_0010", reach::damage_resist::value_0010)
      .value("value_0050", reach::damage_resist::value_0050)
      .value("value_0090", reach::damage_resist::value_0090)
      .value("value_0100", reach::damage_resist::value_0100)
      .value("value_0110", reach::damage_resist::value_0110)
      .value("value_0150", reach::damage_resist::value_0150)
      .value("value_0200", reach::damage_resist::value_0200)
      .value("value_0300", reach::damage_resist::value_0300)
      .value("value_0500", reach::damage_resist::value_0500)
      .value("value_1000", reach::damage_resist::value_1000)
      .value("value_2000", reach::damage_resist::value_2000)
      .value("invulnerable", reach::damage_resist::invulnerable);

   py::enum_<reach::health_multiplier>(m, "HealthMultiplier")
      .value("unchanged", reach::health_multiplier::unchanged)
      .value("value_000", reach::health_multiplier::value_000)
      .value("value_100", reach::health_multiplier::value_100)
      .value("value_150", reach::health_multiplier::value_150)
      .value("value_200", reach::health_multiplier::value_200)
      .value("value_300", reach::health_multiplier::value_300)
      .value("value_400", reach::health_multiplier::value_400);

   py::enum_<reach::health_rate>(m, "HealthRate")
      .value("unchanged", reach::health_rate::unchanged)
      .value("value_n25", reach::health_rate::value_n25)
      .value("value_n10", reach::health_rate::value_n10)
      .value("value_n05", reach::health_rate::value_n05)
      .value("value_000", reach::health_rate::value_000)
      .value("value_050", reach::health_rate::value_050)
      .value("value_090", reach::health_rate::value_090)
      .value("value_100", reach::health_rate::value_100)
      .value("value_110", reach::health_rate::value_110)
      .value("value_200", reach::health_rate::value_200);

   py::enum_<reach::shield_multiplier>(m, "ShieldMultiplier")
      .value("unchanged", reach::shield_multiplier::unchanged)
      .value("value_000", reach::shield_multiplier::value_000)
      .value("value_100", reach::shield_multiplier::value_100)
      .value("value_150", reach::shield_multiplier::value_150)
      .value("value_200", reach::shield_multiplier::value_200)
      .value("value_300", reach::shield_multiplier::value_300)
      .value("value_400", reach::shield_multiplier::value_400);

   py::enum_<reach::shield_rate>(m, "ShieldRate") // also used for PT_Defense::overshieldRate
      .value("unchanged", reach::shield_rate::unchanged)
      .value("value_n25", reach::shield_rate::value_n25)
      .value("value_n10", reach::shield_rate::value_n10)
      .value("value_n05", reach::shield_rate::value_n05)
      .value("value_000", reach::shield_rate::value_000)
      .value("value_010", reach::shield_rate::value_010)
      .value("value_025", reach::shield_rate::value_025)
      .value("value_050", reach::shield_rate::value_050)
      .value("value_075", reach::shield_rate::value_075)
      .value("value_090", reach::shield_rate::value_090)
      .value("value_100", reach::shield_rate::value_100)
      .value("value_110", reach::shield_rate::value_110)
      .value("value_125", reach::shield_rate::value_125)
      .value("value_150", reach::shield_rate::value_150)
      .value("value_200", reach::shield_rate::value_200);

   py::enum_<reach::bool_trait>(m, "BoolTrait") // headshot_immune, assassin_immune, cannot_die_from_damage, grenade_regen, weapon_pickup, abilities_drop_on_death, infinite_ability
      .value("unchanged", reach::bool_trait::unchanged)
      .value("disabled", reach::bool_trait::disabled)
      .value("enabled", reach::bool_trait::enabled);

   py::enum_<reach::vampirism_rate>(m, "VampirismRate")
      .value("unchanged", reach::vampirism_rate::unchanged)
      .value("value_000", reach::vampirism_rate::value_000)
      .value("value_010", reach::vampirism_rate::value_010)
      .value("value_025", reach::vampirism_rate::value_025)
      .value("value_050", reach::vampirism_rate::value_050)
      .value("value_100", reach::vampirism_rate::value_100);

   py::enum_<reach::damage_multiplier>(m, "DamageMultiplier") // damage_mult, melee_mult
      .value("unchanged", reach::damage_multiplier::unchanged)
      .value("value_000", reach::damage_multiplier::value_000)
      .value("value_025", reach::damage_multiplier::value_025)
      .value("value_050", reach::damage_multiplier::value_050)
      .value("value_075", reach::damage_multiplier::value_075)
      .value("value_090", reach::damage_multiplier::value_090)
      .value("value_100", reach::damage_multiplier::value_100)
      .value("value_110", reach::damage_multiplier::value_110)
      .value("value_125", reach::damage_multiplier::value_125)
      .value("value_150", reach::damage_multiplier::value_150)
      .value("value_200", reach::damage_multiplier::value_200)
      .value("value_300", reach::damage_multiplier::value_300)
      .value("instant_kill", reach::damage_multiplier::instant_kill);

   py::enum_<reach::weapon>(m, "Weapon") // PT_Offense::weaponPrimary/weaponSecondary AND ReachLoadout::weaponPrimary/weaponSecondary -- same enum
      .value("random", reach::weapon::random)
      .value("unchanged", reach::weapon::unchanged)
      .value("map_default", reach::weapon::map_default)
      .value("none", reach::weapon::none)
      .value("dmr", reach::weapon::dmr)
      .value("assault_rifle", reach::weapon::assault_rifle)
      .value("plasma_pistol", reach::weapon::plasma_pistol)
      .value("spiker", reach::weapon::spiker)
      .value("energy_sword", reach::weapon::energy_sword)
      .value("magnum", reach::weapon::magnum)
      .value("needler", reach::weapon::needler)
      .value("plasma_rifle", reach::weapon::plasma_rifle)
      .value("rocket_launcher", reach::weapon::rocket_launcher)
      .value("shotgun", reach::weapon::shotgun)
      .value("sniper_rifle", reach::weapon::sniper_rifle)
      .value("spartan_laser", reach::weapon::spartan_laser)
      .value("gravity_hammer", reach::weapon::gravity_hammer)
      .value("plasma_repeater", reach::weapon::plasma_repeater)
      .value("needle_rifle", reach::weapon::needle_rifle)
      .value("focus_rifle", reach::weapon::focus_rifle)
      .value("plasma_launcher", reach::weapon::plasma_launcher)
      .value("concussion_rifle", reach::weapon::concussion_rifle)
      .value("grenade_launcher", reach::weapon::grenade_launcher)
      .value("golf_club", reach::weapon::golf_club)
      .value("fuel_rod_gun", reach::weapon::fuel_rod_gun)
      .value("machine_gun_turret", reach::weapon::machine_gun_turret)
      .value("plasma_cannon", reach::weapon::plasma_cannon)
      .value("target_locator", reach::weapon::target_locator);

   py::enum_<reach::grenade_count>(m, "GrenadeCountTrait") // PT_Offense::grenadeCount only -- ReachLoadout::grenadeCount is a plain int, NOT this enum
      .value("unchanged", reach::grenade_count::unchanged)
      .value("map_default", reach::grenade_count::map_default)
      .value("none", reach::grenade_count::none)
      .value("frag_1", reach::grenade_count::frag_1)
      .value("frag_2", reach::grenade_count::frag_2)
      .value("frag_3", reach::grenade_count::frag_3)
      .value("frag_4", reach::grenade_count::frag_4)
      .value("plasma_1", reach::grenade_count::plasma_1)
      .value("plasma_2", reach::grenade_count::plasma_2)
      .value("plasma_3", reach::grenade_count::plasma_3)
      .value("plasma_4", reach::grenade_count::plasma_4)
      .value("each_1", reach::grenade_count::each_1)
      .value("each_2", reach::grenade_count::each_2)
      .value("each_3", reach::grenade_count::each_3)
      .value("each_4", reach::grenade_count::each_4);

   py::enum_<reach::infinite_ammo>(m, "InfiniteAmmo")
      .value("unchanged", reach::infinite_ammo::unchanged)
      .value("disabled", reach::infinite_ammo::disabled)
      .value("enabled", reach::infinite_ammo::enabled)
      .value("bottomless", reach::infinite_ammo::bottomless);

   py::enum_<reach::ability_usage>(m, "AbilityUsage")
      .value("unchanged", reach::ability_usage::unchanged)
      .value("disabled", reach::ability_usage::disabled)
      .value("not_with_objectives", reach::ability_usage::not_with_objectives)
      .value("enabled", reach::ability_usage::enabled);

   py::enum_<reach::ability>(m, "Ability") // PT_Offense::ability AND ReachLoadout::ability -- same enum
      .value("random", reach::ability::random)
      .value("unchanged", reach::ability::unchanged)
      .value("map_default", reach::ability::map_default)
      .value("none", reach::ability::none)
      .value("sprint", reach::ability::sprint)
      .value("jetpack", reach::ability::jetpack)
      .value("armor_lock", reach::ability::armor_lock)
      .value("unused_power_fist", reach::ability::unused_power_fist)
      .value("active_camo", reach::ability::active_camo)
      .value("unused_ammo_pack", reach::ability::unused_ammo_pack)
      .value("unused_sensor_pack", reach::ability::unused_sensor_pack)
      .value("hologram", reach::ability::hologram)
      .value("evade", reach::ability::evade)
      .value("drop_shield", reach::ability::drop_shield);

   py::enum_<reach::movement_speed>(m, "MovementSpeed")
      .value("unchanged", reach::movement_speed::unchanged)
      .value("value_000", reach::movement_speed::value_000)
      .value("value_025", reach::movement_speed::value_025)
      .value("value_050", reach::movement_speed::value_050)
      .value("value_075", reach::movement_speed::value_075)
      .value("value_090", reach::movement_speed::value_090)
      .value("value_100", reach::movement_speed::value_100)
      .value("value_110", reach::movement_speed::value_110)
      .value("value_120", reach::movement_speed::value_120)
      .value("value_130", reach::movement_speed::value_130)
      .value("value_140", reach::movement_speed::value_140)
      .value("value_150", reach::movement_speed::value_150)
      .value("value_160", reach::movement_speed::value_160)
      .value("value_170", reach::movement_speed::value_170)
      .value("value_180", reach::movement_speed::value_180)
      .value("value_190", reach::movement_speed::value_190)
      .value("value_200", reach::movement_speed::value_200)
      .value("value_300", reach::movement_speed::value_300);

   py::enum_<reach::player_gravity>(m, "PlayerGravity")
      .value("unchanged", reach::player_gravity::unchanged)
      .value("value_050", reach::player_gravity::value_050)
      .value("value_075", reach::player_gravity::value_075)
      .value("value_100", reach::player_gravity::value_100)
      .value("value_150", reach::player_gravity::value_150)
      .value("value_200", reach::player_gravity::value_200);

   py::enum_<reach::vehicle_usage>(m, "VehicleUsage")
      .value("unchanged", reach::vehicle_usage::unchanged)
      .value("none", reach::vehicle_usage::none)
      .value("passenger_only", reach::vehicle_usage::passenger_only)
      .value("driver_only", reach::vehicle_usage::driver_only)
      .value("gunner_only", reach::vehicle_usage::gunner_only)
      .value("no_passenger", reach::vehicle_usage::no_passenger)
      .value("no_driver", reach::vehicle_usage::no_driver)
      .value("no_gunner", reach::vehicle_usage::no_gunner)
      .value("full_use", reach::vehicle_usage::full_use);

   py::enum_<reach::double_jump>(m, "DoubleJump") // unused by the engine, per player_traits.h comment
      .value("unchanged", reach::double_jump::unchanged)
      .value("disabled", reach::double_jump::disabled)
      .value("enabled", reach::double_jump::enabled)
      .value("enabled_plus_lunge", reach::double_jump::enabled_plus_lunge);

   py::enum_<reach::active_camo>(m, "ActiveCamo")
      .value("unchanged", reach::active_camo::unchanged)
      .value("off", reach::active_camo::off)
      .value("worst", reach::active_camo::worst)
      .value("poor", reach::active_camo::poor)
      .value("good", reach::active_camo::good)
      .value("best", reach::active_camo::best);

   py::enum_<reach::visible_identity>(m, "VisibleIdentity") // waypoint, visible_name
      .value("unchanged", reach::visible_identity::unchanged)
      .value("none", reach::visible_identity::none)
      .value("allies", reach::visible_identity::allies)
      .value("everyone", reach::visible_identity::everyone);

   py::enum_<reach::aura>(m, "Aura")
      .value("unchanged", reach::aura::unchanged)
      .value("none", reach::aura::none)
      .value("team_primary", reach::aura::team_primary)
      .value("darken_armor", reach::aura::darken_armor)
      .value("pastel_armor", reach::aura::pastel_armor)
      .value("unknown_5", reach::aura::unknown_5)
      .value("unknown_6", reach::aura::unknown_6);

   py::enum_<reach::forced_color>(m, "ForcedColor")
      .value("unchanged", reach::forced_color::unchanged)
      .value("none", reach::forced_color::none)
      .value("red", reach::forced_color::red)
      .value("blue", reach::forced_color::blue)
      .value("green", reach::forced_color::green)
      .value("orange", reach::forced_color::orange)
      .value("purple", reach::forced_color::purple)
      .value("gold", reach::forced_color::gold)
      .value("brown", reach::forced_color::brown)
      .value("pink", reach::forced_color::pink)
      .value("white", reach::forced_color::white)
      .value("black", reach::forced_color::black)
      .value("zombie", reach::forced_color::zombie)
      .value("very_marginally_more_vibrant_pink", reach::forced_color::very_marginally_more_vibrant_pink);

   py::enum_<reach::radar_state>(m, "RadarState")
      .value("unchanged", reach::radar_state::unchanged)
      .value("off", reach::radar_state::off)
      .value("allies", reach::radar_state::allies)
      .value("normal", reach::radar_state::normal)
      .value("enhanced", reach::radar_state::enhanced);

   py::enum_<reach::radar_range>(m, "RadarRange")
      .value("unchanged", reach::radar_range::unchanged)
      .value("meters_010", reach::radar_range::meters_010)
      .value("meters_015", reach::radar_range::meters_015)
      .value("meters_025", reach::radar_range::meters_025)
      .value("meters_050", reach::radar_range::meters_050)
      .value("meters_075", reach::radar_range::meters_075)
      .value("meters_100", reach::radar_range::meters_100)
      .value("meters_150", reach::radar_range::meters_150);

   using PT_Defense    = decltype(ReachPlayerTraits::defense);
   using PT_Offense    = decltype(ReachPlayerTraits::offense);
   using PT_Movement   = decltype(ReachPlayerTraits::movement);
   using PT_Appearance = decltype(ReachPlayerTraits::appearance);
   using PT_Sensors    = decltype(ReachPlayerTraits::sensors);

   py::class_<PT_Defense>(m, "PlayerTraitsDefense")
      .def_readwrite("damage_resist", &PT_Defense::damageResist)
      .def_readwrite("health_mult", &PT_Defense::healthMult)
      .def_readwrite("health_rate", &PT_Defense::healthRate)
      .def_readwrite("shield_mult", &PT_Defense::shieldMult)
      .def_readwrite("shield_rate", &PT_Defense::shieldRate)
      .def_readwrite("overshield_rate", &PT_Defense::overshieldRate)
      .def_readwrite("headshot_immune", &PT_Defense::headshotImmune)
      .def_readwrite("vampirism", &PT_Defense::vampirism)
      .def_readwrite("assassin_immune", &PT_Defense::assassinImmune)
      .def_readwrite("cannot_die_from_damage", &PT_Defense::cannotDieFromDamage);

   py::class_<PT_Offense>(m, "PlayerTraitsOffense")
      .def_readwrite("damage_mult", &PT_Offense::damageMult)
      .def_readwrite("melee_mult", &PT_Offense::meleeMult)
      .def_readwrite("weapon_primary", &PT_Offense::weaponPrimary)
      .def_readwrite("weapon_secondary", &PT_Offense::weaponSecondary)
      .def_readwrite("grenade_count", &PT_Offense::grenadeCount)
      .def_readwrite("infinite_ammo", &PT_Offense::infiniteAmmo)
      .def_readwrite("grenade_regen", &PT_Offense::grenadeRegen)
      .def_readwrite("weapon_pickup", &PT_Offense::weaponPickup)
      .def_readwrite("ability_usage", &PT_Offense::abilityUsage)
      .def_readwrite("abilities_drop_on_death", &PT_Offense::abilitiesDropOnDeath)
      .def_readwrite("infinite_ability", &PT_Offense::infiniteAbility)
      .def_readwrite("ability", &PT_Offense::ability);

   py::class_<PT_Movement>(m, "PlayerTraitsMovement")
      .def_readwrite("speed", &PT_Movement::speed)
      .def_readwrite("gravity", &PT_Movement::gravity)
      .def_readwrite("vehicle_usage", &PT_Movement::vehicleUsage)
      .def_readwrite("double_jump", &PT_Movement::doubleJump)
      .def_readwrite("jump_height", &PT_Movement::jumpHeight);

   py::class_<PT_Appearance>(m, "PlayerTraitsAppearance")
      .def_readwrite("active_camo", &PT_Appearance::activeCamo)
      .def_readwrite("waypoint", &PT_Appearance::waypoint)
      .def_readwrite("visible_name", &PT_Appearance::visibleName)
      .def_readwrite("aura", &PT_Appearance::aura)
      .def_readwrite("forced_color", &PT_Appearance::forcedColor);

   py::class_<PT_Sensors>(m, "PlayerTraitsSensors")
      .def_readwrite("radar_state", &PT_Sensors::radarState)
      .def_readwrite("radar_range", &PT_Sensors::radarRange)
      .def_readwrite("directional_damage_indicator", &PT_Sensors::directionalDamageIndicator);

   py::class_<ReachPlayerTraits>(m, "PlayerTraits")
      .def_readwrite("defense", &ReachPlayerTraits::defense)
      .def_readwrite("offense", &ReachPlayerTraits::offense)
      .def_readwrite("movement", &ReachPlayerTraits::movement)
      .def_readwrite("appearance", &ReachPlayerTraits::appearance)
      .def_readwrite("sensors", &ReachPlayerTraits::sensors);

   // ---- loadouts ----------------------------------------------------------------------------

   py::class_<ReachLoadout>(m, "Loadout")
      .def_readwrite("visible", &ReachLoadout::visible)
      .def_readwrite("name_index", &ReachLoadout::nameIndex)
      .def_readwrite("weapon_primary", &ReachLoadout::weaponPrimary)
      .def_readwrite("weapon_secondary", &ReachLoadout::weaponSecondary)
      .def_readwrite("ability", &ReachLoadout::ability)
      .def_readwrite("grenade_count", &ReachLoadout::grenadeCount);

   py::class_<ReachLoadoutPalette>(m, "LoadoutPalette")
      .def("loadout", [](ReachLoadoutPalette& p, size_t i) -> ReachLoadout& { return index_into(p.loadouts, i); },
         py::return_value_policy::reference_internal)
      .def_property_readonly("loadout_count", [](ReachLoadoutPalette& p) { return p.loadouts.size(); });

   // ---- powerups / map permissions / player rating / TU1 --------------------------------

   py::class_<ReachPowerupData>(m, "PowerupData")
      .def_readwrite("duration", &ReachPowerupData::duration)
      .def_readwrite("traits", &ReachPowerupData::traits);

   py::enum_<reach::map_permission_type>(m, "MapPermissionType")
      .value("only_these_maps", reach::map_permission_type::only_these_maps)
      .value("never_these_maps", reach::map_permission_type::never_these_maps);

   py::class_<ReachMapPermissions>(m, "MapPermissions")
      .def_readwrite("map_ids", &ReachMapPermissions::mapIDs)
      .def_readwrite("type", &ReachMapPermissions::type);

   py::class_<ReachPlayerRatingParams>(m, "PlayerRatingParams")
      .def_readwrite("values", &ReachPlayerRatingParams::values)
      .def_readwrite("show_in_scoreboard", &ReachPlayerRatingParams::showInScoreboard);

   py::class_<ReachGameVariantTU1Options>(m, "TU1Options")
      .def_readwrite("flags", &ReachGameVariantTU1Options::flags)
      .def_readwrite("precision_bloom", &ReachGameVariantTU1Options::precisionBloom)
      .def_readwrite("active_camo_energy_curve_min", &ReachGameVariantTU1Options::activeCamoEnergyCurveMin)
      .def_readwrite("active_camo_energy_curve_max", &ReachGameVariantTU1Options::activeCamoEnergyCurveMax)
      .def_readwrite("armor_lock_damage_drain", &ReachGameVariantTU1Options::armorLockDamageDrain)
      .def_readwrite("armor_lock_damage_drain_limit", &ReachGameVariantTU1Options::armorLockDamageDrainLimit)
      .def_readwrite("magnum_damage", &ReachGameVariantTU1Options::magnumDamage)
      .def_readwrite("magnum_fire_delay", &ReachGameVariantTU1Options::magnumFireDelay)
      .def("is_vanilla", &ReachGameVariantTU1Options::is_vanilla);

   // ---- custom game options: general/respawn/social/map/team/loadouts -------------------

   py::class_<ReachCGGeneralOptions>(m, "GeneralOptions")
      .def_readwrite("flags", &ReachCGGeneralOptions::flags)
      .def_readwrite("time_limit", &ReachCGGeneralOptions::timeLimit)
      .def_readwrite("round_limit", &ReachCGGeneralOptions::roundLimit)
      .def_readwrite("rounds_to_win", &ReachCGGeneralOptions::roundsToWin)
      .def_readwrite("sudden_death_time", &ReachCGGeneralOptions::suddenDeathTime)
      .def_readwrite("grace_period", &ReachCGGeneralOptions::gracePeriod);

   py::class_<ReachCGRespawnOptions>(m, "RespawnOptions")
      .def_readwrite("flags", &ReachCGRespawnOptions::flags)
      .def_readwrite("lives_per_round", &ReachCGRespawnOptions::livesPerRound)
      .def_readwrite("team_lives_per_round", &ReachCGRespawnOptions::teamLivesPerRound)
      .def_readwrite("respawn_time", &ReachCGRespawnOptions::respawnTime)
      .def_readwrite("suicide_penalty", &ReachCGRespawnOptions::suicidePenalty)
      .def_readwrite("betrayal_penalty", &ReachCGRespawnOptions::betrayalPenalty)
      .def_readwrite("respawn_growth", &ReachCGRespawnOptions::respawnGrowth)
      .def_readwrite("loadout_cam_time", &ReachCGRespawnOptions::loadoutCamTime)
      .def_readwrite("traits_duration", &ReachCGRespawnOptions::traitsDuration)
      .def_readwrite("traits", &ReachCGRespawnOptions::traits);

   py::class_<ReachCGSocialOptions>(m, "SocialOptions")
      .def_readwrite("observers", &ReachCGSocialOptions::observers)
      .def_readwrite("team_changes", &ReachCGSocialOptions::teamChanges)
      .def_readwrite("flags", &ReachCGSocialOptions::flags);

   py::enum_<reach::weapon_set>(m, "WeaponSet")
      .value("random", reach::weapon_set::random)
      .value("map_default", reach::weapon_set::map_default)
      .value("none", reach::weapon_set::none)
      .value("human", reach::weapon_set::human)
      .value("covenant", reach::weapon_set::covenant)
      .value("no_snipers", reach::weapon_set::no_snipers)
      .value("rocket_launchers", reach::weapon_set::rocket_launchers)
      .value("no_power_weapons", reach::weapon_set::no_power_weapons)
      .value("juggernaut", reach::weapon_set::juggernaut)
      .value("slayer_pro", reach::weapon_set::slayer_pro)
      .value("rifles_only", reach::weapon_set::rifles_only)
      .value("mid_range_only", reach::weapon_set::mid_range_only)
      .value("long_range_only", reach::weapon_set::long_range_only)
      .value("sniper_rifles", reach::weapon_set::sniper_rifles)
      .value("melee", reach::weapon_set::melee)
      .value("energy_swords", reach::weapon_set::energy_swords)
      .value("gravity_hammers", reach::weapon_set::gravity_hammers)
      .value("mass_destruction", reach::weapon_set::mass_destruction);

   py::enum_<reach::vehicle_set>(m, "VehicleSet")
      .value("map_default", reach::vehicle_set::map_default)
      .value("mongooses", reach::vehicle_set::mongooses)
      .value("warthogs", reach::vehicle_set::warthogs)
      .value("no_aircraft", reach::vehicle_set::no_aircraft)
      .value("only_aircraft", reach::vehicle_set::only_aircraft)
      .value("no_tanks", reach::vehicle_set::no_tanks)
      .value("only_tanks", reach::vehicle_set::only_tanks)
      .value("no_light_ground", reach::vehicle_set::no_light_ground)
      .value("only_light_ground", reach::vehicle_set::only_light_ground)
      .value("no_covenant", reach::vehicle_set::no_covenant)
      .value("all_covenant", reach::vehicle_set::all_covenant)
      .value("no_human", reach::vehicle_set::no_human)
      .value("all_human", reach::vehicle_set::all_human)
      .value("none", reach::vehicle_set::none)
      .value("all", reach::vehicle_set::all);

   py::class_<ReachCGMapOptions>(m, "MapOptions")
      .def_readwrite("flags", &ReachCGMapOptions::flags)
      .def_readwrite("base_traits", &ReachCGMapOptions::baseTraits)
      .def_readwrite("weapon_set", &ReachCGMapOptions::weaponSet)
      .def_readwrite("vehicle_set", &ReachCGMapOptions::vehicleSet)
      .def_property_readonly("powerup_red", [](ReachCGMapOptions& o) -> ReachPowerupData& { return o.powerups.red; }, py::return_value_policy::reference_internal)
      .def_property_readonly("powerup_blue", [](ReachCGMapOptions& o) -> ReachPowerupData& { return o.powerups.blue; }, py::return_value_policy::reference_internal)
      .def_property_readonly("powerup_yellow", [](ReachCGMapOptions& o) -> ReachPowerupData& { return o.powerups.yellow; }, py::return_value_policy::reference_internal);

   py::enum_<ReachCGTeamOptions::scoring_modes>(m, "TeamScoringMode")
      .value("sum", ReachCGTeamOptions::scoring_modes::sum)
      .value("minimum", ReachCGTeamOptions::scoring_modes::minimum)
      .value("maximum", ReachCGTeamOptions::scoring_modes::maximum);

   py::enum_<ReachCGTeamOptions::team_designator_switch_type>(m, "TeamDesignatorSwitchType")
      .value("none", ReachCGTeamOptions::team_designator_switch_type::none)
      .value("random", ReachCGTeamOptions::team_designator_switch_type::random)
      .value("rotate", ReachCGTeamOptions::team_designator_switch_type::rotate);

   py::class_<ReachCGTeamOptions>(m, "TeamOptions")
      .def_readwrite("scoring", &ReachCGTeamOptions::scoring)
      .def_readwrite("species", &ReachCGTeamOptions::species)
      .def_readwrite("designator_switch_type", &ReachCGTeamOptions::designatorSwitchType)
      .def("team", [](ReachCGTeamOptions& o, size_t i) -> ReachTeamData& {
            if (i >= sizeof(o.teams) / sizeof(o.teams[0]))
               throw py::index_error(std::to_string(i));
            return o.teams[i];
         }, py::return_value_policy::reference_internal)
      .def_property_readonly("team_count", [](ReachCGTeamOptions& o) { return sizeof(o.teams) / sizeof(o.teams[0]); });

   py::class_<ReachCGLoadoutOptions>(m, "LoadoutOptions")
      .def_readwrite("flags", &ReachCGLoadoutOptions::flags)
      .def("palette", [](ReachCGLoadoutOptions& o, size_t i) -> ReachLoadoutPalette& { return index_into(o.palettes, i); },
         py::return_value_policy::reference_internal)
      .def_property_readonly("palette_count", [](ReachCGLoadoutOptions& o) { return o.palettes.size(); });

   py::class_<ReachCustomGameOptions>(m, "CustomGameOptions")
      .def_readwrite("general", &ReachCustomGameOptions::general)
      .def_readwrite("respawn", &ReachCustomGameOptions::respawn)
      .def_readwrite("social", &ReachCustomGameOptions::social)
      .def_readwrite("map", &ReachCustomGameOptions::map)
      .def_readonly("team", &ReachCustomGameOptions::team) // not copy-assignable (contains ReachStringTable, which has const members)
      .def_readwrite("loadouts", &ReachCustomGameOptions::loadouts);

   // ---- Firefight ------------------------------------------------------------------------

   py::enum_<reach::ai_vision>(m, "AIVision")
      .value("unchanged", reach::ai_vision::unchanged)
      .value("normal", reach::ai_vision::normal)
      .value("blind", reach::ai_vision::blind)
      .value("nearsighted", reach::ai_vision::nearsighted)
      .value("eagle_eye", reach::ai_vision::eagle_eye);

   py::enum_<reach::ai_hearing>(m, "AIHearing")
      .value("unchanged", reach::ai_hearing::unchanged)
      .value("normal", reach::ai_hearing::normal)
      .value("deaf", reach::ai_hearing::deaf)
      .value("sharp", reach::ai_hearing::sharp);

   py::enum_<reach::ai_luck>(m, "AILuck")
      .value("unchanged", reach::ai_luck::unchanged)
      .value("normal", reach::ai_luck::normal)
      .value("unlucky", reach::ai_luck::unlucky)
      .value("lucky", reach::ai_luck::lucky)
      .value("leprechaun", reach::ai_luck::leprechaun);

   py::enum_<reach::ai_shootiness>(m, "AIShootiness")
      .value("unchanged", reach::ai_shootiness::unchanged)
      .value("normal", reach::ai_shootiness::normal)
      .value("marksman", reach::ai_shootiness::marksman)
      .value("trigger_happy", reach::ai_shootiness::trigger_happy);

   py::enum_<reach::ai_grenades>(m, "AIGrenades")
      .value("unchanged", reach::ai_grenades::unchanged)
      .value("normal", reach::ai_grenades::normal)
      .value("none", reach::ai_grenades::none)
      .value("catch_skull", reach::ai_grenades::catch_skull);

   py::class_<ReachFirefightWaveTraits>(m, "FirefightWaveTraits")
      .def_readwrite("vision", &ReachFirefightWaveTraits::vision)
      .def_readwrite("hearing", &ReachFirefightWaveTraits::hearing)
      .def_readwrite("luck", &ReachFirefightWaveTraits::luck)
      .def_readwrite("shootiness", &ReachFirefightWaveTraits::shootiness)
      .def_readwrite("grenades", &ReachFirefightWaveTraits::grenades)
      .def_readwrite("dont_drop_equipment", &ReachFirefightWaveTraits::dontDropEquipment)
      .def_readwrite("assassin_immunity", &ReachFirefightWaveTraits::assassinImmunity)
      .def_readwrite("headshot_immunity", &ReachFirefightWaveTraits::headshotImmunity)
      .def_readwrite("damage_resist", &ReachFirefightWaveTraits::damageResist)
      .def_readwrite("damage_mult", &ReachFirefightWaveTraits::damageMult);

   py::enum_<reach::firefight_skull>(m, "FirefightSkull")
      .value("iron", reach::firefight_skull::iron)
      .value("black_eye", reach::firefight_skull::black_eye)
      .value("tough_luck", reach::firefight_skull::tough_luck)
      .value("catch_", reach::firefight_skull::catch_)
      .value("fog", reach::firefight_skull::fog)
      .value("famine", reach::firefight_skull::famine)
      .value("thunderstorm", reach::firefight_skull::thunderstorm)
      .value("tilt", reach::firefight_skull::tilt)
      .value("mythic", reach::firefight_skull::mythic)
      .value("assassin", reach::firefight_skull::assassin)
      .value("blind", reach::firefight_skull::blind)
      .value("cowbell", reach::firefight_skull::cowbell)
      .value("grunt_birthday_party", reach::firefight_skull::grunt_birthday_party)
      .value("iwhbyd", reach::firefight_skull::iwhbyd)
      .value("red", reach::firefight_skull::red)
      .value("yellow", reach::firefight_skull::yellow)
      .value("blue", reach::firefight_skull::blue);

   py::enum_<reach::firefight_squad>(m, "FirefightSquad")
      .value("none", reach::firefight_squad::none)
      .value("brutes", reach::firefight_squad::brutes)
      .value("brute_kill_team", reach::firefight_squad::brute_kill_team)
      .value("brute_patrol", reach::firefight_squad::brute_patrol)
      .value("brute_infantry", reach::firefight_squad::brute_infantry)
      .value("brute_tactical", reach::firefight_squad::brute_tactical)
      .value("brute_chieftains", reach::firefight_squad::brute_chieftains)
      .value("elites", reach::firefight_squad::elites)
      .value("elite_patrol", reach::firefight_squad::elite_patrol)
      .value("elite_infantry", reach::firefight_squad::elite_infantry)
      .value("elite_airborne", reach::firefight_squad::elite_airborne)
      .value("elite_tactical", reach::firefight_squad::elite_tactical)
      .value("elite_spec_ops", reach::firefight_squad::elite_spec_ops)
      .value("engineers", reach::firefight_squad::engineers)
      .value("elite_generals", reach::firefight_squad::elite_generals)
      .value("grunts", reach::firefight_squad::grunts)
      .value("hunter_kill_team", reach::firefight_squad::hunter_kill_team)
      .value("hunter_patrol", reach::firefight_squad::hunter_patrol)
      .value("hunter_strike_team", reach::firefight_squad::hunter_strike_team)
      .value("jackal_patrol", reach::firefight_squad::jackal_patrol)
      .value("elite_strike_team", reach::firefight_squad::elite_strike_team)
      .value("skirmisher_patrol", reach::firefight_squad::skirmisher_patrol)
      .value("hunters", reach::firefight_squad::hunters)
      .value("jackal_snipers", reach::firefight_squad::jackal_snipers)
      .value("jackals", reach::firefight_squad::jackals)
      .value("hunter_infantry", reach::firefight_squad::hunter_infantry)
      .value("guta", reach::firefight_squad::guta)
      .value("skirmishers", reach::firefight_squad::skirmishers)
      .value("hunter_tactical", reach::firefight_squad::hunter_tactical)
      .value("skirmisher_infantry", reach::firefight_squad::skirmisher_infantry)
      .value("heretics", reach::firefight_squad::heretics)
      .value("heretic_snipers", reach::firefight_squad::heretic_snipers)
      .value("heretic_heavy", reach::firefight_squad::heretic_heavy);

   py::class_<ReachFirefightWave>(m, "FirefightWave")
      .def_readwrite("uses_dropship", &ReachFirefightWave::usesDropship)
      .def_readwrite("ordered_squads", &ReachFirefightWave::orderedSquads)
      .def_readwrite("squad_count", &ReachFirefightWave::squadCount)
      .def("squad", [](ReachFirefightWave& w, size_t i) -> ReachFirefightWave::squad_type_t& {
            // w.squads is a raw C array (squad_type_t squads[12]), no .size() -- can't use index_into<>()
            // here (see the README's "Raw C arrays vs std::array" implementation note).
            if (i >= sizeof(w.squads) / sizeof(w.squads[0]))
               throw py::index_error(std::to_string(i));
            return w.squads[i];
         }, py::return_value_policy::reference_internal)
      .def_property_readonly("squad_capacity", [](ReachFirefightWave& w) { return sizeof(w.squads) / sizeof(w.squads[0]); });

   py::class_<ReachFirefightRound>(m, "FirefightRound")
      .def_readwrite("skulls", &ReachFirefightRound::skulls)
      .def_readwrite("wave_initial", &ReachFirefightRound::waveInitial)
      .def_readwrite("wave_main", &ReachFirefightRound::waveMain)
      .def_readwrite("wave_boss", &ReachFirefightRound::waveBoss);

   py::class_<ReachFirefightCustomSkull>(m, "FirefightCustomSkull")
      .def_readwrite("traits_spartan", &ReachFirefightCustomSkull::traitsSpartan)
      .def_readwrite("traits_elite", &ReachFirefightCustomSkull::traitsElite)
      .def_readwrite("traits_wave", &ReachFirefightCustomSkull::traitsWave);

   py::class_<GameVariantDataFirefight>(m, "FirefightData")
      .def_readonly("options", &GameVariantDataFirefight::options) // not copy-assignable (contains ReachStringTable via team names), same as MultiplayerData.options
      .def_readwrite("scenario_flags", &GameVariantDataFirefight::scenarioFlags)
      .def_readwrite("mcc_extension_version", &GameVariantDataFirefight::mccExtensionVersion)
      .def_readwrite("wave_limit", &GameVariantDataFirefight::waveLimit)
      .def_readwrite("bonus_target", &GameVariantDataFirefight::bonusTarget)
      .def_readwrite("elite_kill_bonus", &GameVariantDataFirefight::eliteKillBonus)
      .def_readwrite("starting_lives_spartan", &GameVariantDataFirefight::startingLivesSpartan)
      .def_readwrite("starting_lives_elite", &GameVariantDataFirefight::startingLivesElite)
      .def_readwrite("max_spartan_extra_lives", &GameVariantDataFirefight::maxSpartanExtraLives)
      .def_readwrite("generator_count", &GameVariantDataFirefight::generatorCount)
      .def_readwrite("base_traits_spartan", &GameVariantDataFirefight::baseTraitsSpartan)
      .def_readwrite("base_traits_elite", &GameVariantDataFirefight::baseTraitsElite)
      .def_readwrite("base_traits_wave", &GameVariantDataFirefight::baseTraitsWave)
      .def_readwrite("elite_respawn_options", &GameVariantDataFirefight::eliteRespawnOptions)
      .def("custom_skull", [](GameVariantDataFirefight& ff, size_t i) -> ReachFirefightCustomSkull& {
            // ff.customSkulls is a raw C array (ReachFirefightCustomSkull customSkulls[3]), no .size() --
            // can't use index_into<>() here (see the README's "Raw C arrays vs std::array" note).
            if (i >= sizeof(ff.customSkulls) / sizeof(ff.customSkulls[0]))
               throw py::index_error(std::to_string(i));
            return ff.customSkulls[i];
         }, py::return_value_policy::reference_internal, "0=red, 1=yellow, 2=blue -- see GameVariantDataFirefight::custom_skull")
      .def("round", [](GameVariantDataFirefight& ff, size_t i) -> ReachFirefightRound& {
            // ff.rounds is a raw C array (ReachFirefightRound rounds[3]), same reasoning as custom_skull() above.
            if (i >= sizeof(ff.rounds) / sizeof(ff.rounds[0]))
               throw py::index_error(std::to_string(i));
            return ff.rounds[i];
         }, py::return_value_policy::reference_internal, "A Firefight Set is 3 Rounds (0/1/2) plus a bonus wave -- see firefight_round.h's file comment")
      .def_readwrite("bonus_wave_duration", &GameVariantDataFirefight::bonusWaveDuration)
      .def_readwrite("bonus_wave_skulls", &GameVariantDataFirefight::bonusWaveSkulls)
      .def_readwrite("bonus_wave", &GameVariantDataFirefight::bonusWave)
      .def_property_readonly("variant_header", [](GameVariantDataFirefight& ff) -> ReachUGCHeader& { return ff.variantHeader; }, py::return_value_policy::reference_internal);

   // ---- script-defined content: forge labels, scripted options/traits/stats/HUD widgets ---
   // ---- (GameVariantDataMultiplayer::scriptData / scriptContent)                          ---

   m.def("object_type_count", &object_type_count,
      "Number of entries in the map object-type list (Megalo::enums::object_type) -- the same "
      "list ForgeLabel.required_object_type / MultiplayerData.used_object_type_indices index into.");
   m.def("object_type_name", &object_type_name, py::arg("index"),
      "Friendly display name for a map object-type index -- falls back to the raw internal name "
      "when no friendly name is set, matching ui/widgets/mp_object_type_combobox.h's own fallback. "
      "Raises IndexError if `index` is out of range.");

   py::enum_<Megalo::const_team>(m, "ConstTeam")
      .value("none", Megalo::const_team::none)
      .value("team_1", Megalo::const_team::team_1)
      .value("team_2", Megalo::const_team::team_2)
      .value("team_3", Megalo::const_team::team_3)
      .value("team_4", Megalo::const_team::team_4)
      .value("team_5", Megalo::const_team::team_5)
      .value("team_6", Megalo::const_team::team_6)
      .value("team_7", Megalo::const_team::team_7)
      .value("team_8", Megalo::const_team::team_8)
      .value("neutral", Megalo::const_team::neutral);

   py::class_<Megalo::ReachForgeLabel>(m, "ForgeLabel")
      .def_property_readonly("name", [](Megalo::ReachForgeLabel& l) -> ReachString* { return l.name; }, py::return_value_policy::reference_internal)
      .def_readwrite("requirements", &Megalo::ReachForgeLabel::requirements) // bitflags: 0x01=objects_of_type, 0x02=assigned_team, 0x04=number -- see Megalo::ReachForgeLabel::requirement_flags
      .def_readwrite("required_object_type", &Megalo::ReachForgeLabel::requiredObjectType) // -1 = none; index into the map's object type list, no name list bound yet
      .def_readwrite("required_team", &Megalo::ReachForgeLabel::requiredTeam)
      .def_readwrite("required_number", &Megalo::ReachForgeLabel::requiredNumber)
      .def_readwrite("map_must_have_at_least", &Megalo::ReachForgeLabel::mapMustHaveAtLeast);

   py::class_<Megalo::HUDWidgetDeclaration>(m, "HUDWidgetDeclaration")
      .def_readwrite("position", &Megalo::HUDWidgetDeclaration::position); // values above 11 are invalid and will cause MCC to fail to load/display the variant

   py::enum_<ReachMegaloGameStat::Format>(m, "ScriptedStatFormat")
      .value("number", ReachMegaloGameStat::Format::number)
      .value("number_with_sign", ReachMegaloGameStat::Format::number_with_sign)
      .value("percentage", ReachMegaloGameStat::Format::percentage)
      .value("time", ReachMegaloGameStat::Format::time);

   py::enum_<ReachMegaloGameStat::Sort>(m, "ScriptedStatSort")
      .value("ascending", ReachMegaloGameStat::Sort::ascending)
      .value("ignored", ReachMegaloGameStat::Sort::ignored)
      .value("descending", ReachMegaloGameStat::Sort::descending)
      .value("obsolete_2", ReachMegaloGameStat::Sort::obsolete_2);

   py::class_<ReachMegaloGameStat>(m, "ScriptedStat")
      .def_property_readonly("name", [](ReachMegaloGameStat& s) -> ReachString* { return s.name; }, py::return_value_policy::reference_internal)
      .def_readwrite("format", &ReachMegaloGameStat::format)
      .def_readwrite("sort_order", &ReachMegaloGameStat::sortOrder)
      .def_readwrite("group_by_team", &ReachMegaloGameStat::groupByTeam);

   py::class_<ReachMegaloOptionValueEntry>(m, "ScriptedOptionValue")
      .def_property_readonly("name", [](ReachMegaloOptionValueEntry& v) -> ReachString* { return v.name; }, py::return_value_policy::reference_internal)
      .def_property_readonly("desc", [](ReachMegaloOptionValueEntry& v) -> ReachString* { return v.desc; }, py::return_value_policy::reference_internal)
      .def_readwrite("value", &ReachMegaloOptionValueEntry::value);

   py::class_<ReachMegaloOption>(m, "ScriptedOption")
      .def_property_readonly("name", [](ReachMegaloOption& o) -> ReachString* { return o.name; }, py::return_value_policy::reference_internal)
      .def_property_readonly("desc", [](ReachMegaloOption& o) -> ReachString* { return o.desc; }, py::return_value_policy::reference_internal)
      .def_readwrite("is_range", &ReachMegaloOption::isRange)
      .def("value", [](ReachMegaloOption& o, size_t i) -> ReachMegaloOptionValueEntry& {
            if (i >= o.values.size())
               throw py::index_error(std::to_string(i));
            return *o.values[i];
         }, py::return_value_policy::reference_internal)
      .def_property_readonly("value_count", [](ReachMegaloOption& o) { return o.values.size(); })
      .def_property_readonly("range_default", [](ReachMegaloOption& o) -> ReachMegaloOptionValueEntry* { return o.rangeDefault; }, py::return_value_policy::reference_internal)
      .def_property_readonly("range_min", [](ReachMegaloOption& o) -> ReachMegaloOptionValueEntry* { return o.rangeMin; }, py::return_value_policy::reference_internal)
      .def_property_readonly("range_max", [](ReachMegaloOption& o) -> ReachMegaloOptionValueEntry* { return o.rangeMax; }, py::return_value_policy::reference_internal)
      .def_readwrite("default_value_index", &ReachMegaloOption::defaultValueIndex)
      .def_readwrite("range_current", &ReachMegaloOption::rangeCurrent)
      .def_readwrite("current_value_index", &ReachMegaloOption::currentValueIndex);

   py::class_<ReachMegaloPlayerTraits, ReachPlayerTraits>(m, "ScriptedPlayerTraits")
      .def_property_readonly("name", [](ReachMegaloPlayerTraits& t) -> ReachString* { return t.name; }, py::return_value_policy::reference_internal)
      .def_property_readonly("desc", [](ReachMegaloPlayerTraits& t) -> ReachString* { return t.desc; }, py::return_value_policy::reference_internal);

   // ---- GameVariantDataMultiplayer / GameVariant -----------------------------------------

   // ReachContentAuthor / ReachUGCHeader back the *real*, GUI-facing "Metadata" page
   // (ui/main_window/page_multiplayer_metadata.ui: title/description/engineIcon/engineCategory/
   // author/editor), as opposed to localized_name/localized_desc/localized_category below (which
   // back the Script Editor's separate "Metadata Strings" page). See mide's game.schema.yml
   // Metadata/meta split note for the fuller explanation of why these are two different things.
   py::class_<ReachContentAuthor>(m, "ContentAuthor")
      // Latin-1, not UTF-8 -- matches the GUI's own QString::fromLatin1(...->createdBy.author)
      // (page_multiplayer_metadata.cpp). A raw std::string(a.author) here would hand pybind11's
      // std::string->str caster bytes it assumes are UTF-8, which throws UnicodeDecodeError on
      // any high-bit byte that isn't a valid UTF-8 continuation sequence (blank_mp.bin's unset
      // author field hits this in practice).
      .def_property("author_name",
         [](ReachContentAuthor& a) { return QString::fromLatin1(a.author).toStdString(); },
         // Same QString::toLatin1() encoding the GUI's own authorGamertag/editorGamertag QLineEdit
         // handlers use (page_multiplayer_metadata.cpp) -- set_author_name() itself just truncates/
         // null-pads into the 16-byte (15 char + terminator) buffer, no encoding conversion of its own.
         [](ReachContentAuthor& a, const std::string& name) { a.set_author_name(QString::fromUtf8(name.c_str()).toLatin1().constData()); })
      .def_readonly("timestamp", &ReachContentAuthor::timestamp, "Seconds since 1970-01-01 00:00:00 GMT.")
      .def_readonly("xuid", &ReachContentAuthor::xuid)
      .def("has_xuid", &ReachContentAuthor::has_xuid);

   py::class_<ReachUGCHeader>(m, "UGCHeader")
      .def_property("title",
         [](ReachUGCHeader& h) { return QString::fromUtf16(h.title).toStdString(); },
         [](ReachUGCHeader& h, const std::string& text) { h.set_title(QString::fromUtf8(text.c_str()).toStdU16String().c_str()); })
      .def_property("description",
         [](ReachUGCHeader& h) { return QString::fromUtf16(h.description).toStdString(); },
         [](ReachUGCHeader& h, const std::string& text) { h.set_description(QString::fromUtf8(text.c_str()).toStdU16String().c_str()); })
      .def_readwrite("engine_icon", &ReachUGCHeader::engineIcon)
      .def_readwrite("engine_category", &ReachUGCHeader::engineCategory)
      .def_readonly("created_by", &ReachUGCHeader::createdBy, py::return_value_policy::reference_internal)
      .def_readonly("modified_by", &ReachUGCHeader::modifiedBy, py::return_value_policy::reference_internal);

   // ---- space usage / trigger-condition-action stats (game_variants/types/multiplayer.h) -----
   // Mirrors ui/script_editor/bottom_bar.cpp's "Space usage" meter and per-metric counters.

   py::class_<ReachMPSizeData>(m, "MPSizeData")
      .def_property_readonly("bits", [](ReachMPSizeData& d) {
         py::dict out;
         out["maximum"]         = d.bits.maximum;
         out["header"]          = d.bits.header;
         out["header_strings"]  = d.bits.header_strings;
         out["cg_options"]      = d.bits.cg_options;
         out["team_config"]     = d.bits.team_config;
         out["script_traits"]   = d.bits.script_traits;
         out["script_options"]  = d.bits.script_options;
         out["script_strings"]  = d.bits.script_strings;
         out["option_toggles"]  = d.bits.option_toggles;
         out["rating_params"]   = d.bits.rating_params;
         out["map_perms"]       = d.bits.map_perms;
         out["script_content"]  = d.bits.script_content;
         out["script_stats"]    = d.bits.script_stats;
         out["script_widgets"]  = d.bits.script_widgets;
         out["forge_labels"]    = d.bits.forge_labels;
         out["title_update_1"]  = d.bits.title_update_1;
         return out;
      }, "Per-section bit usage, matching the Script and Data Editor's 'Space usage' meter segments.")
      .def_property_readonly("counts", [](ReachMPSizeData& d) {
         py::dict out;
         out["conditions"]     = d.counts.conditions;
         out["actions"]        = d.counts.actions;
         out["triggers"]       = d.counts.triggers;
         out["forge_labels"]   = d.counts.forge_labels;
         out["strings"]        = d.counts.strings;
         out["script_options"] = d.counts.script_options;
         out["script_stats"]   = d.counts.script_stats;
         out["script_traits"]  = d.counts.script_traits;
         out["script_widgets"] = d.counts.script_widgets;
         return out;
      }, "Entry counts, matching the Script and Data Editor's Triggers/Conditions/Actions/... metric widgets.")
      .def("total_bits", &ReachMPSizeData::total_bits);

   // ---- Megalo trigger/opcode/argument object graph (README.md Roadmap item 3) -----------
   // ---- Read-only: the real engine Trigger/Opcode/Condition/Action/OpcodeArgValue classes, ---
   // ---- not a re-derived approximation -- see AST.md's "engine AST" section for the full    ---
   // ---- design writeup, and mide/megalo_ast/engine.py for the Python-side pydantic wrapper. ---

   py::enum_<Megalo::variable_type>(m, "VariableType")
      .value("scalar", Megalo::variable_type::scalar)
      .value("player", Megalo::variable_type::player)
      .value("object", Megalo::variable_type::object)
      .value("team", Megalo::variable_type::team)
      .value("timer", Megalo::variable_type::timer)
      .value("not_a_variable", Megalo::variable_type::not_a_variable);

   py::enum_<Megalo::variable_scope>(m, "VariableScope")
      .value("global", Megalo::variable_scope::global)
      .value("player", Megalo::variable_scope::player)
      .value("object", Megalo::variable_scope::object)
      .value("team", Megalo::variable_scope::team)
      .value("temporary", Megalo::variable_scope::temporary)
      .value("not_a_scope", Megalo::variable_scope::not_a_scope);

   py::enum_<Megalo::OpcodeFuncToScriptMapping::mapping_type>(m, "OpcodeMappingType")
      .value("none", Megalo::OpcodeFuncToScriptMapping::mapping_type::none)
      .value("assign", Megalo::OpcodeFuncToScriptMapping::mapping_type::assign)
      .value("compare", Megalo::OpcodeFuncToScriptMapping::mapping_type::compare)
      .value("function", Megalo::OpcodeFuncToScriptMapping::mapping_type::function)
      .value("property_get", Megalo::OpcodeFuncToScriptMapping::mapping_type::property_get)
      .value("property_set", Megalo::OpcodeFuncToScriptMapping::mapping_type::property_set,
         "opcode should be modified as `context.name = argument` -- every property_get has a "
         "matching property_set but not every property_set has a property_get.");

   py::enum_<Megalo::block_type>(m, "TriggerBlockType")
      .value("normal", Megalo::block_type::normal, "Not a loop -- a plain sequential trigger.")
      .value("for_each_player", Megalo::block_type::for_each_player)
      .value("for_each_player_randomly", Megalo::block_type::for_each_player_randomly)
      .value("for_each_team", Megalo::block_type::for_each_team)
      .value("for_each_object", Megalo::block_type::for_each_object)
      .value("for_each_object_with_label", Megalo::block_type::for_each_object_with_label);

   py::enum_<Megalo::entry_type>(m, "TriggerEntryType")
      .value("normal", Megalo::entry_type::normal)
      .value("subroutine", Megalo::entry_type::subroutine, "Preserves iterator values from outer loops.")
      .value("on_init", Megalo::entry_type::on_init)
      .value("on_local_init", Megalo::entry_type::on_local_init, "Unverified; not used in Bungie gametypes.")
      .value("on_host_migration", Megalo::entry_type::on_host_migration)
      .value("on_object_death", Megalo::entry_type::on_object_death)
      .value("local", Megalo::entry_type::local)
      .value("pregame", Megalo::entry_type::pregame);

   py::class_<Megalo::TriggerEntryPoints>(m, "TriggerEntryPoints",
      "The event-type -> trigger-index lookup table the ENGINE uses to find e.g. 'the pregame "
      "trigger' at runtime -- a second, redundant place event-bound wiring lives, alongside each "
      "Trigger's own entry_type field (confirmed both get set together by compile_script() for a "
      "real 'on pregame: ...' block -- keep them in sync, same category of multi-location-write "
      "gotcha as engine_icon/engine_category elsewhere in this binding; MultiplayerData."
      "bind_trigger_as_event() does both atomically, prefer it over setting these separately).")
      .def("get_index_of_event", &Megalo::TriggerEntryPoints::get_index_of_event,
         "-1 (none) if no trigger is registered for this event type, or if entry_type doesn't correspond to an event at all (e.g. normal/subroutine).")
      .def("set_index_of_event", &Megalo::TriggerEntryPoints::set_index_of_event, py::arg("entry_type"), py::arg("trigger_index"),
         "Does nothing for an entry_type that isn't an event type. Pass -1 to clear.");

   py::class_<Megalo::VariableScopeIndicatorValue>(m, "VariableScopeIndicatorValue")
      .def_readonly("format", &Megalo::VariableScopeIndicatorValue::format,
         "Decompiled-code format template, interpreted manually -- %w = the 'which' as a string, %i = index as a number.")
      .def_readonly("format_english", &Megalo::VariableScopeIndicatorValue::format_english)
      .def_property_readonly("is_readonly", &Megalo::VariableScopeIndicatorValue::is_readonly)
      .def_property_readonly("is_variable_scope", &Megalo::VariableScopeIndicatorValue::is_variable_scope)
      .def_property_readonly("has_index", &Megalo::VariableScopeIndicatorValue::has_index)
      .def_property_readonly("has_which", &Megalo::VariableScopeIndicatorValue::has_which);

   py::class_<Megalo::OpcodeArgTypeinfo>(m, "OpcodeArgTypeinfo")
      .def_readonly("internal_name", &Megalo::OpcodeArgTypeinfo::internal_name)
      .def_readonly("friendly_name", &Megalo::OpcodeArgTypeinfo::friendly_name)
      .def_readonly("description", &Megalo::OpcodeArgTypeinfo::description)
      .def_property_readonly("is_variable", &Megalo::OpcodeArgTypeinfo::is_variable)
      .def_property_readonly("can_have_variables", &Megalo::OpcodeArgTypeinfo::can_have_variables)
      .def("create", [](const Megalo::OpcodeArgTypeinfo& t) -> std::unique_ptr<Megalo::OpcodeArgValue> { return std::unique_ptr<Megalo::OpcodeArgValue>((t.factory)()); },
         "A brand-new, default-valued instance of this argument type (e.g. a fresh ScalarVariable "
         "for a 'number' argument) -- the same factory the engine itself uses when loading/compiling. "
         "Returned as an owning handle (std::unique_ptr on the C++ side) so passing it straight into "
         "Opcode.add_argument() safely hands off ownership with no double-free risk -- see AST.md's "
         "'Constructing new opcodes' section for the full construction workflow this is one step of.");

   py::class_<Megalo::OpcodeArgBase>(m, "OpcodeArgBase")
      .def_readonly("name", &Megalo::OpcodeArgBase::name)
      .def_readonly("is_out_variable", &Megalo::OpcodeArgBase::is_out_variable)
      .def_property_readonly("typeinfo", [](const Megalo::OpcodeArgBase& a) -> const Megalo::OpcodeArgTypeinfo& { return a.typeinfo; },
         py::return_value_policy::reference_internal); // reference member -- can't def_readonly a pointer-to-reference, same category of gotcha as this file's other def_readonly/def_readwrite notes

   py::class_<Megalo::OpcodeFuncToScriptMapping>(m, "OpcodeFuncToScriptMapping")
      .def_readonly("type", &Megalo::OpcodeFuncToScriptMapping::type)
      .def_readonly("primary_name", &Megalo::OpcodeFuncToScriptMapping::primary_name)
      .def_readonly("secondary_name", &Megalo::OpcodeFuncToScriptMapping::secondary_name)
      .def_readonly("arg_context", &Megalo::OpcodeFuncToScriptMapping::arg_context)
      .def_readonly("arg_name", &Megalo::OpcodeFuncToScriptMapping::arg_name)
      .def_readonly("arg_operator", &Megalo::OpcodeFuncToScriptMapping::arg_operator);

   py::class_<Megalo::OpcodeBase>(m, "OpcodeBase")
      .def_readonly("name", &Megalo::OpcodeBase::name)
      .def_readonly("desc", &Megalo::OpcodeBase::desc)
      .def_readonly("format", &Megalo::OpcodeBase::format)
      .def_readonly("arguments", &Megalo::OpcodeBase::arguments, // vector<OpcodeArgBase> -- read-only metadata, fine as an stl.h by-value copy (unlike the mutable-object-list cases elsewhere in this file, nothing here is ever written back)
         "Per-argument metadata (name/typeinfo), positionally matching Opcode.argument(i)'s values.")
      .def_readonly("mapping", &Megalo::OpcodeBase::mapping);

   py::class_<Megalo::OpcodeArgValue, py::smart_holder>(m, "OpcodeArgValue")
      .def("to_string", [](const Megalo::OpcodeArgValue& v) { std::string out; v.to_string(out); return out; },
         "A human-readable ENGLISH DESCRIPTION of this argument (e.g. \"the global number at index 0\" -- "
         "exact wording depends on the concrete type), matching what RVT's own GUI trigger-list panel shows. "
         "NOT Megalo script syntax -- use decompile() for that.")
      .def("decompile", [](Megalo::OpcodeArgValue& v, GameVariant& variant) { Megalo::Decompiler d(variant); v.decompile(d); return d.current_content; }, py::arg("variant"),
         "The real Megalo script syntax for this argument, e.g. 'global.number[0]', 'current_player', "
         "'\"some string\"' -- the same text decompile_script() would produce for it, since this calls the "
         "same virtual Decompiler-based rendering (correct for every concrete argument type without needing "
         "its own C++ class bound -- see AST.md). Needs the owning GameVariant since some argument types "
         "resolve through it (e.g. script string references); pass the same GameVariant this opcode came from.")
      .def("get_variable_type", &Megalo::OpcodeArgValue::get_variable_type)
      .def("clone", [](const Megalo::OpcodeArgValue& v) -> std::unique_ptr<Megalo::OpcodeArgValue> { return std::unique_ptr<Megalo::OpcodeArgValue>(v.clone()); },
         "A deep copy of this argument (same concrete type, same field values) as a new, owning "
         "handle -- pass straight into Opcode.add_argument(). The 'duplicate an existing argument "
         "then tweak its fields' half of constructing a new opcode -- see AST.md.");

   py::class_<Megalo::Variable, Megalo::OpcodeArgValue, py::smart_holder>(m, "Variable")
      .def_property_readonly("scope", [](const Megalo::Variable& v) -> const Megalo::VariableScopeIndicatorValue* { return v.scope; },
         py::return_value_policy::reference, "None until this variable has been fully resolved (should always be set for a loaded, valid script).")
      .def_readwrite("which", &Megalo::Variable::which, "Which scoping variable this is nested under (e.g. which player, for a per-player variable) -- meaning depends on `scope`.")
      .def_readwrite("index", &Megalo::Variable::index)
      .def("get_variable_typeinfo", &Megalo::Variable::get_variable_typeinfo, py::return_value_policy::reference,
         "Which concrete variable flavor this is (its internal_name/friendly_name) -- resolves virtually, so this works without needing this type's own concrete C++ class bound.")
      .def("is_none", &Megalo::Variable::is_none)
      .def("is_transient", &Megalo::Variable::is_transient)
      .def("copy_from", [](Megalo::Variable& v, const Megalo::Variable& other) { v.copy(&other); }, py::arg("other"),
         "Copies scope/which/index/object from `other`, which MUST be the exact same concrete "
         "Variable subtype (e.g. two ScalarVariables) -- the underlying Variable::copy() only "
         "checks this via a plain assert(), compiled out entirely in a Release build, so passing a "
         "mismatched type (e.g. copying a ScalarVariable into a live ObjectVariable) silently "
         "corrupts state instead of raising -- confirmed directly, not just inferred from reading "
         "the assert. Callers are responsible for only ever passing a matching type. The only way "
         "to populate an embedded, initially-scope=None Variable member this binding exposes no "
         "constructor or scope setter for (e.g. ShapeArgument.radius/.length/.top/.bottom, each a "
         "live ScalarVariable& reference into the ShapeArgument's own storage, not a standalone "
         "value you could otherwise clone-and-reassign). Source `other` the same way as everywhere "
         "else in this binding: a real, already-valid Variable found in the loaded script (or one "
         "of its own siblings, once populated) -- not constructed from nothing.\n\n"
         "IMPORTANT: also copies `other`'s own `object` (a refcount_ptr into one of `other`'s own "
         "'indexed_data'-scoped tables, e.g. a script_option[N] reference -- see clear_object()'s "
         "own docstring for why this matters after retargeting `index`).")
      .def("clear_object", [](Megalo::Variable& v) { v.object = nullptr; },
         "Resets `object` to null. Confirmed a real, previously-undiscovered native bug this fixes "
         "around: for a 'indexed_data'-scoped Variable (e.g. script_option[N], whose own "
         "VariableScopeIndicatorValue is built via make_indexed_data_indicator() -- see "
         "opcode_arg_types/variables/number.cpp) that was CLONED from a real, already-loaded "
         "example and then retargeted to a different `index`, `Variable::write()` (base.cpp) still "
         "prefers a non-null `object`'s own `->index` over the Variable's own freshly-set `index` "
         "when serializing -- `object` only gets (re)computed from `index` during `read()`, so a "
         "clone made via clone-and-retarget (not round-tripped through read()) keeps the ORIGINAL "
         "template's own stale `object`, silently writing the ORIGINAL index instead of the "
         "retargeted one, and desyncing the bitstream for everything written after it (its own "
         "`object->index` can need a different bit-width to represent than what `index_bits()` "
         "assumed for the retargeted value). Call this immediately after retargeting `index` on any "
         "clone of an 'indexed_data'-scoped Variable.")
      .def("set_scope_by_format", [](Megalo::Variable& v, const std::string& format, int32_t index) {
            for (auto* s : v.type.scopes) {
               if (s->format && format == s->format) {
                  v.scope  = s;
                  v.which  = 0;
                  v.index  = (int16_t)index;
                  v.object = nullptr;
                  return;
               }
            }
            throw std::runtime_error(
               "Variable.set_scope_by_format(): no scope with that format string exists for this "
               "variable's own concrete type (see get_variable_typeinfo())"
            );
         }, py::arg("format"), py::arg("index"),
         "Constructs a Variable reference DIRECTLY from one of its own concrete type's known scopes "
         "(matched by exact `format` string, e.g. 'script_option[%i]' -- see a real scope's own "
         ".scope.format for the exact spelling a given family uses), with no existing loaded example "
         "to clone-and-retarget from at all. Exists for the same reason clear_object()/AnyVariable."
         "wrap() do: this binding otherwise only ever lets Python reach a variable-family's own "
         "scopes by cloning one that's already present somewhere in an already-loaded script (see "
         "_retarget()'s own docstring in megalo_compiler.py) -- for a variant whose script genuinely "
         "has NO existing example of a given (typeinfo, scope) pairing anywhere (confirmed a real, "
         "previously-blocking case: a Shape's own dimension argument sourced from script_option[N] "
         "-- a 'number'-typeinfo ScalarVariable -- in a script that only ever references "
         "script_option[] through OTHER typeinfos, like a plain condition compare), there was no way "
         "to build one at all. `format` is matched against `VariableScopeIndicatorValueList::scopes` "
         "(this concrete type's own fixed, static list -- see base.h), so passing a format string "
         "that belongs to a DIFFERENT variable family (e.g. a player-scope format on a "
         "ScalarVariable) correctly raises rather than silently doing nothing. Sets `object` to null "
         "(this is never a clone of an existing 'indexed_data'-scoped reference, so there is no stale "
         "`object` to worry about -- see clear_object()'s own docstring) and `which` to 0 (unused for "
         "an 'indexed_data'/'none'-index-type scope; a `which`-bearing scope, e.g. a plain "
         "player/object/team pool reference, is reachable via clone-and-retarget already and doesn't "
         "need this).");

   // pybind11's polymorphic downcasting matches the EXACT dynamic C++ type against the registry --
   // it does not walk up to the nearest registered ancestor when the concrete leaf type itself isn't
   // registered (confirmed directly: without these 5, isinstance(arg, Variable) was False even for
   // plain "global.number[0]"/"current_player.number[0]", since their concrete class is
   // OpcodeArgValueScalar, not Variable itself). These 5 are the actual concrete classes backing
   // every Variable instance a real script produces (opcode_arg_types/variables/{number,object,
   // player,team,timer}.h) -- no new fields needed, everything's inherited from Variable above.
   py::class_<Megalo::OpcodeArgValueScalar, Megalo::Variable, py::smart_holder>(m, "ScalarVariable");
   py::class_<Megalo::OpcodeArgValueObject, Megalo::Variable, py::smart_holder>(m, "ObjectVariable");
   py::class_<Megalo::OpcodeArgValuePlayer, Megalo::Variable, py::smart_holder>(m, "PlayerVariable");
   py::class_<Megalo::OpcodeArgValueTeam, Megalo::Variable, py::smart_holder>(m, "TeamVariable");
   py::class_<Megalo::OpcodeArgValueTimer, Megalo::Variable, py::smart_holder>(m, "TimerVariable");
   // These two are argument types that can hold "any variable of several possible types" (e.g. the
   // "Compare" condition's operands) -- they derive from OpcodeArgValue directly, not Variable, so
   // they never expose scope/which/index; registered purely so isinstance() identifies them instead
   // of falling back to plain OpcodeArgValue, same reasoning as the 5 above.
   py::class_<Megalo::OpcodeArgValuePlayerOrGroup, Megalo::OpcodeArgValue, py::smart_holder>(m, "PlayerOrGroupVariable")
      .def_property_readonly("variable", [](const Megalo::OpcodeArgValuePlayerOrGroup& v) -> Megalo::Variable* { return v.variable; }, py::return_value_policy::reference,
         "The actual resolved Variable this wraps (e.g. a PlayerVariable for 'current_player'), or None.");
   py::class_<Megalo::OpcodeArgValueAnyVariable, Megalo::OpcodeArgValue, py::smart_holder>(m, "AnyVariable")
      .def_property_readonly("variable", [](const Megalo::OpcodeArgValueAnyVariable& v) -> Megalo::Variable* { return v.variable; }, py::return_value_policy::reference,
         "The actual resolved Variable this wraps (e.g. a ScalarVariable for 'current_player.number[0]'), or "
         "None -- specifically None when this argument is a constant/game-state value rather than a variable "
         "reference (get_variable_type() is not_a_variable in that case).")
      .def("wrap", [](Megalo::OpcodeArgValueAnyVariable& av, const Megalo::OpcodeArgValue& v) {
         auto* cloned = v.clone();
         auto* as_variable = dynamic_cast<Megalo::Variable*>(cloned);
         if (!as_variable) {
            delete cloned;
            throw std::runtime_error("AnyVariable.wrap(): value is not a Variable-derived argument");
         }
         if (av.variable)
            delete av.variable;
         av.variable = as_variable;
      }, py::arg("value"),
         "Clones `value` (any Variable-derived argument -- ScalarVariable/ObjectVariable/etc, e.g. one "
         "sourced from a _scan_templates()-style template stored raw/unwrapped) and adopts the clone as "
         "this AnyVariable's own .variable. Fixes a real, previously-undiscovered native-adjacent bug: "
         "Opcode.add_argument() stores whatever concrete OpcodeArgValue subtype it's given verbatim, with "
         "no type-checking against the argument slot's own declared typeinfo -- passing a bare Variable "
         "(e.g. a ScalarVariable template cloned straight from a format-string token's own raw .value, "
         "which is never wrapped in an AnyVariable to begin with) into a slot whose metadata says "
         "'_any_variable' silently builds a structurally wrong opcode: Action::write()/Condition::write() "
         "call that argument's own polymorphic write(), which for a bare Variable skips the 3-bit type-tag "
         "prefix OpcodeArgValueAnyVariable::write() normally emits -- desyncing the bitstream for every "
         "opcode written after it, with no crash and no ASan report (not memory corruption, just the wrong "
         "concrete C++ type stored in that slot). Always construct via a fresh 'AnyVariable' typeinfo."
         "create() + .wrap(value) instead of ever passing a bare Variable directly to add_argument() for "
         "an '_any_variable'-typed slot.");

   py::class_<Megalo::Opcode, py::smart_holder>(m, "Opcode")
      .def_property("function",
         [](const Megalo::Opcode& o) -> const Megalo::OpcodeBase* { return o.function; },
         [](Megalo::Opcode& o, const Megalo::OpcodeBase* base) { o.function = base; },
         py::return_value_policy::reference,
         "This opcode's metadata (name/format/mapping) -- shared across every opcode of this kind, not "
         "owned by this instance. Writable (assign one of action_function(i)/condition_function(i)'s "
         "results, matching this Opcode's own Action/Condition-ness) -- the first step of constructing a "
         "new opcode from scratch, see AST.md's 'Constructing new opcodes' section. Changing it does NOT "
         "resize .arguments to match the new function's arity -- call add_argument()/clear_arguments() "
         "yourself to match, same as everywhere else in this binding (caller's responsibility).")
      .def("argument", [](Megalo::Opcode& o, size_t i) -> Megalo::OpcodeArgValue* { return index_into(o.arguments, i); }, py::return_value_policy::reference_internal,
         "Returns a Variable when this argument is a variable reference (pybind11 downcasts automatically), a plain OpcodeArgValue otherwise -- "
         "the plain-OpcodeArgValue case still has a fully correct to_string(), just no structured scope/which/index (see AST.md).")
      .def_property_readonly("argument_count", [](Megalo::Opcode& o) { return o.arguments.size(); })
      .def("add_argument", [](Megalo::Opcode& o, std::unique_ptr<Megalo::OpcodeArgValue> arg) { o.arguments.push_back(arg.release()); }, py::arg("value"),
         "Appends value (from OpcodeArgTypeinfo.create() or OpcodeArgValue.clone(), never a reference "
         "borrowed from another opcode's own argument() -- pybind11 will refuse the ownership transfer "
         "for a non-owned instance) to .arguments. This Opcode takes ownership -- it will delete `value` "
         "when it's itself destroyed, so never add_argument() the same object twice or to two opcodes.")
      .def("clear_arguments", [](Megalo::Opcode& o) { for (auto* a : o.arguments) delete a; o.arguments.clear(); },
         "Deletes every current argument and empties .arguments -- use before repopulating with add_argument() "
         "if this opcode's function is changing to one with a different arity/argument types.")
      .def("clone", [](const Megalo::Opcode& o) -> std::unique_ptr<Megalo::Opcode> { return std::unique_ptr<Megalo::Opcode>(o.clone()); },
         "A deep copy of this opcode (same function, same argument values, each argument itself cloned) "
         "as a new, owning handle -- pass straight into CodeBlock.add_opcode(). The 'duplicate an existing "
         "opcode then tweak its fields' construction workflow -- see AST.md.")
      .def("to_string", [](const Megalo::Opcode& o) { std::string out; o.to_string(out); return out; },
         "A human-readable ENGLISH DESCRIPTION of this whole condition/action, matching what RVT's own GUI "
         "trigger-list panel shows (e.g. 'current_player is an Elite.', 'Switch current_player to Elite Tier "
         "1.'). NOT Megalo script syntax -- use decompile() for that.")
      .def("decompile", [](Megalo::Opcode& o, GameVariant& variant) { Megalo::Decompiler d(variant); o.decompile(d); return d.current_content; }, py::arg("variant"),
         "The real Megalo script syntax for this one condition/action, e.g. 'current_player.is_elite()', "
         "'current_player.set_loadout_palette(elite_tier_1)' -- the same text decompile_script() emits per "
         "opcode, MINUS the surrounding 'if ... then'/'end' block wrapping (that's reconstructed at the "
         "CodeBlock/Trigger level from or_group/action-index relationships, not stored per-opcode -- see "
         "Condition.or_group's docstring and AST.md). Returns the literal string 'nop' for any opcode whose "
         "function.mapping.type is OpcodeMappingType.none (e.g. 'Run Nested Trigger'/'Run Inline Trigger' -- "
         "their real 'for each ... do ... end'/inlined-subroutine text only exists as a special case in the "
         "full CodeBlock/Trigger decompile walk, not per-opcode -- this is the engine's own documented "
         "behavior, not a binding gap, see opcode.cpp's OpcodeBase::decompile()). Needs the owning "
         "GameVariant, same reason as OpcodeArgValue.decompile().");

   py::class_<Megalo::Condition, Megalo::Opcode, py::smart_holder>(m, "Condition")
      .def(py::init<>(), "A brand-new, blank Condition (no function, no arguments) -- see AST.md's "
         "'Constructing new opcodes' section for how to turn one into a real, working condition.")
      .def_readwrite("inverted", &Megalo::Condition::inverted, "True for 'not <condition>'.")
      .def_readwrite("or_group", &Megalo::Condition::or_group,
         "Conditions compiled from the same source 'if'/'and'/'or' chain that share an or_group are OR-linked; consecutive different or_groups are AND-linked. "
         "This is how nested if-blocks in decompiled text are actually represented in the engine -- as a flat run of guard conditions, not a nested tree (see AST.md). "
         "Writable, but changing it changes which sibling conditions this one is grouped with -- get the whole containing trigger's or_group layout right, not just this one field, or you'll change the compiled logic's meaning.")
      .def_readwrite("action", &Megalo::Condition::action,
         "Index (into the owning CodeBlock's flat opcode-index space) of the action this condition gates. "
         "Writable -- out-of-range values are the caller's responsibility, same as everywhere else in this binding (see README.md's Implementation notes).");

   py::class_<Megalo::Action, Megalo::Opcode, py::smart_holder>(m, "Action")
      .def(py::init<>(), "A brand-new, blank Action (no function, no arguments) -- see AST.md's "
         "'Constructing new opcodes' section for how to turn one into a real, working action.");

   py::class_<Megalo::CodeBlock>(m, "CodeBlock")
      .def("opcode", [](Megalo::CodeBlock& c, size_t i) -> Megalo::Opcode* { return index_into(c.opcodes, i); }, py::return_value_policy::reference_internal,
         "Condition or Action, in the same flat program order the engine executes them in.")
      .def_property_readonly("opcode_count", [](Megalo::CodeBlock& c) { return c.opcodes.size(); })
      .def("add_opcode", [](Megalo::CodeBlock& c, std::unique_ptr<Megalo::Opcode> op) { c.opcodes.push_back(op.release()); }, py::arg("opcode"),
         "Appends opcode (a Condition/Action from Condition()/Action() + .function/.add_argument(), or "
         "an existing opcode's .clone()) to the end of this trigger's flat opcode list. This CodeBlock "
         "takes ownership. No further bookkeeping needed before GameVariant.save() -- write() itself "
         "regenerates every trigger's raw serialized layout (start indices/counts, and each new "
         "Condition's own .action gated-index) fresh from the live .opcodes state on every save, "
         "confirmed by reading code_block.cpp's generate_flat_opcode_lists() (NOT assumed -- an "
         "earlier pass wrongly assumed this needed manual raw-array management). The one exception: "
         "a new Condition's .or_group is NOT auto-assigned -- set it yourself (e.g. one past every "
         "existing condition's or_group in this trigger, to AND-link it as its own independent group) "
         "before saving, see AST.md.");

   py::class_<Megalo::Trigger, Megalo::CodeBlock>(m, "Trigger")
      .def_property_readonly("block_type", [](const Megalo::Trigger& t) { return t.blockType.value; })
      .def_property_readonly("entry_type", [](const Megalo::Trigger& t) { return t.entryType.value; })
      .def_property_readonly("forge_label", [](Megalo::Trigger& t) -> Megalo::ReachForgeLabel* { return t.forgeLabel.operator->(); }, py::return_value_policy::reference_internal,
         "The forge label this trigger's 'for each object with label ...' selects on, or None -- only meaningful when block_type is for_each_object_with_label.");

   // The engine's own fixed metadata tables for every real opcode (see OpcodeBase's own docstring
   // above) -- the "what functions/conditions exist to assign to Opcode.function" half of
   // constructing a new opcode. Index-accessor pattern, same as everywhere else in this file
   // (index_into()) rather than returning a Python list, for the same reason: no copy, no
   // ownership ambiguity. 107 actions, 18 conditions -- cheap to linear-scan by .name from Python.
   m.def("action_function_count", []() { return Megalo::actionFunctionList.size(); });
   m.def("action_function", [](size_t i) -> const Megalo::OpcodeBase& { return index_into(Megalo::actionFunctionList, i); }, py::return_value_policy::reference,
      "One of the engine's 107 fixed ActionFunction definitions by index -- assign to an Action's .function.");
   m.def("condition_function_count", []() { return Megalo::conditionFunctionList.size(); });
   m.def("condition_function", [](size_t i) -> const Megalo::OpcodeBase& { return index_into(Megalo::conditionFunctionList, i); }, py::return_value_policy::reference,
      "One of the engine's 18 fixed ConditionFunction definitions by index -- assign to a Condition's .function.");

   // ---- OpcodeArgValue leaf types beyond the variables/ family (opcode_arg_types/*.h) -----
   // ---- Read-write where the field is a plain value (mutating an already-loaded opcode's ---
   // ---- argument and then .save()-ing the variant works -- write() just serializes         ---
   // ---- whatever's currently in memory, see AST.md's "Two-way mutation" section). Every one ---
   // ---- of these still has a correct to_string()/decompile() inherited from OpcodeArgValue, ---
   // ---- so binding a type here only ADDS structured field access, it was already readable.  ---
   // ---- NOT bound: OpcodeArgValueFormatString(Persistent) (owns a fixed array of further     ---
   // ---- OpcodeArgValue* sub-arguments via OpcodeStringToken -- the send_incident()/          ---
   // ---- set_objective_text()-style "%s"/"%n" format-string-with-inserted-args mechanism) and ---
   // ---- OpcodeArgValueMegaloScope (embeds a full CodeBlock by value -- the "Run Inline       ---
   // ---- Trigger"/`begin ... end` argument). Both need more design thought than a mechanical  ---
   // ---- field-by-field binding (the former for pointer-ownership across the token array, the ---
   // ---- latter because it's a second, argument-level place a nested opcode list can live,    ---
   // ---- alongside Trigger itself -- see AST.md's flat-vs-nested design note) -- deliberately  ---
   // ---- deferred rather than bound carelessly.

   py::class_<Megalo::OpcodeArgValueConstBool, Megalo::OpcodeArgValue, py::smart_holder>(m, "ConstBoolArgument")
      .def_readwrite("value", &Megalo::OpcodeArgValueConstBool::value);

   py::class_<Megalo::OpcodeArgValueConstSInt8, Megalo::OpcodeArgValue, py::smart_holder>(m, "ConstSInt8Argument")
      .def_readwrite("value", &Megalo::OpcodeArgValueConstSInt8::value);

   py::class_<Megalo::OpcodeArgValueTimerRate, Megalo::OpcodeArgValue, py::smart_holder>(m, "TimerRateArgument")
      .def_readwrite("value", &Megalo::OpcodeArgValueTimerRate::value,
         "Raw index (0-31) into the engine's internal percentages lookup table -- NOT the percent "
         "itself (e.g. '-100%' is some index, not -100). Use to_string()/decompile() for the real "
         "percent text. Writable: that table isn't bound, but it doesn't need to be -- the same "
         "try-values-until-decompile()-matches search every other enum-style argument here uses "
         "(see megalo_compiler.py's _enum_value_of()) finds the index for a given percent. Only 27 "
         "of the 32 possible indexes are real rates; an index past those decompiles as 'invalid[N]'.");

   py::class_<Megalo::OpcodeArgValueFireteamList, Megalo::OpcodeArgValue, py::smart_holder>(m, "FireteamListArgument")
      .def_readwrite("value", &Megalo::OpcodeArgValueFireteamList::value);

   py::class_<Megalo::OpcodeArgValueIncident, Megalo::OpcodeArgValue, py::smart_holder>(m, "IncidentArgument")
      .def_readwrite("value", &Megalo::OpcodeArgValueIncident::value, "-1 = none.");

   py::class_<Megalo::OpcodeArgValueObjectType, Megalo::OpcodeArgValue, py::smart_holder>(m, "ObjectTypeArgument")
      .def_readwrite("value", &Megalo::OpcodeArgValueObjectType::value,
         "-1 = none; index into the map's object-type list -- see object_type_name()/object_type_count().");

   py::class_<Megalo::OpcodeArgValueSound, Megalo::OpcodeArgValue, py::smart_holder>(m, "SoundArgument")
      .def_readwrite("value", &Megalo::OpcodeArgValueSound::value, "-1 = none; index into the engine's built-in sound list.");

   py::class_<Megalo::OpcodeArgValueVariantStringID, Megalo::OpcodeArgValue, py::smart_holder>(m, "VariantStringIDArgument")
      .def_readwrite("value", &Megalo::OpcodeArgValueVariantStringID::value,
         "-1 = none; index into MultiplayerData.script_strings.");

   py::class_<Megalo::OpcodeArgValueVector3, Megalo::OpcodeArgValue, py::smart_holder>(m, "Vector3Argument")
      .def_property("x", [](const Megalo::OpcodeArgValueVector3& v) { return v.value.x; }, [](Megalo::OpcodeArgValueVector3& v, int8_t x) { v.value.x = x; })
      .def_property("y", [](const Megalo::OpcodeArgValueVector3& v) { return v.value.y; }, [](Megalo::OpcodeArgValueVector3& v, int8_t y) { v.value.y = y; })
      .def_property("z", [](const Megalo::OpcodeArgValueVector3& v) { return v.value.z; }, [](Megalo::OpcodeArgValueVector3& v, int8_t z) { v.value.z = z; });

   py::enum_<Megalo::OpcodeArgValueBaseIndex::index_quirk>(m, "IndexQuirk")
      .value("none", Megalo::OpcodeArgValueBaseIndex::index_quirk::none)
      .value("presence", Megalo::OpcodeArgValueBaseIndex::index_quirk::presence, "Index value is preceded by an 'is none' bit.")
      .value("reference", Megalo::OpcodeArgValueBaseIndex::index_quirk::reference)
      .value("offset", Megalo::OpcodeArgValueBaseIndex::index_quirk::offset)
      .value("word", Megalo::OpcodeArgValueBaseIndex::index_quirk::word);

   py::class_<Megalo::OpcodeArgValueBaseIndex, Megalo::OpcodeArgValue, py::smart_holder>(m, "BaseIndexArgument")
      .def_readonly("name", &Megalo::OpcodeArgValueBaseIndex::name)
      .def_readonly("max", &Megalo::OpcodeArgValueBaseIndex::max)
      .def_readonly("quirk", &Megalo::OpcodeArgValueBaseIndex::quirk)
      .def_readwrite("value", &Megalo::OpcodeArgValueBaseIndex::value);

   py::class_<Megalo::OpcodeArgValueTrigger, Megalo::OpcodeArgValueBaseIndex, py::smart_holder>(m, "TriggerArgument",
      "value is the index of the Trigger this argument references, e.g. the target of a 'Run Nested "
      "Trigger' action's argument -- MultiplayerData.trigger(value) resolves it. This is the primitive "
      "the flat opcode graph would need to reconstruct for-each/nested-block structure in a future pass "
      "(see AST.md's 'How the two AST layers relate').");
   py::class_<Megalo::OpcodeArgValueRequisitionPalette, Megalo::OpcodeArgValueBaseIndex, py::smart_holder>(m, "RequisitionPaletteArgument",
      "Development leftover -- see the C++ header's own comment (\"later used in Halo 4?\").");

   py::class_<Megalo::OpcodeArgValueEnumSuperclass, Megalo::OpcodeArgValue, py::smart_holder>(m, "EnumArgument")
      .def_readwrite("value", &Megalo::OpcodeArgValueEnumSuperclass::value,
         "Raw index into this argument's own name table -- use to_string()/decompile() for the resolved name.");

   py::class_<Megalo::OpcodeArgValueAddWeaponEnum, Megalo::OpcodeArgValueEnumSuperclass, py::smart_holder>(m, "AddWeaponEnumArgument");
   py::class_<Megalo::OpcodeArgValueAttachPositionEnum, Megalo::OpcodeArgValueEnumSuperclass, py::smart_holder>(m, "AttachPositionEnumArgument");
   py::class_<Megalo::OpcodeArgValueCHUDDestinationEnum, Megalo::OpcodeArgValueEnumSuperclass, py::smart_holder>(m, "CHUDDestinationEnumArgument");
   py::class_<Megalo::OpcodeArgValueCompareOperatorEnum, Megalo::OpcodeArgValueEnumSuperclass, py::smart_holder>(m, "CompareOperatorEnumArgument")
      .def("invert", &Megalo::OpcodeArgValueCompareOperatorEnum::invert);
   py::class_<Megalo::OpcodeArgValueDropWeaponEnum, Megalo::OpcodeArgValueEnumSuperclass, py::smart_holder>(m, "DropWeaponEnumArgument");
   py::class_<Megalo::OpcodeArgValueGrenadeTypeEnum, Megalo::OpcodeArgValueEnumSuperclass, py::smart_holder>(m, "GrenadeTypeEnumArgument");
   py::class_<Megalo::OpcodeArgValueMathOperatorEnum, Megalo::OpcodeArgValueEnumSuperclass, py::smart_holder>(m, "MathOperatorEnumArgument")
      .def("is_abs_assign", &Megalo::OpcodeArgValueMathOperatorEnum::is_abs_assign)
      .def("uses_mcc_exclusive_data", &Megalo::OpcodeArgValueMathOperatorEnum::uses_mcc_exclusive_data);
   py::class_<Megalo::OpcodeArgValuePickupPriorityEnum, Megalo::OpcodeArgValueEnumSuperclass, py::smart_holder>(m, "PickupPriorityEnumArgument");
   py::class_<Megalo::OpcodeArgValueTeamAllianceStatus, Megalo::OpcodeArgValueEnumSuperclass, py::smart_holder>(m, "TeamAllianceStatusArgument");
   py::class_<Megalo::OpcodeArgValueWaypointPriorityEnum, Megalo::OpcodeArgValueEnumSuperclass, py::smart_holder>(m, "WaypointPriorityEnumArgument");
   py::class_<Megalo::OpcodeArgValueWeaponSlotEnum, Megalo::OpcodeArgValueEnumSuperclass, py::smart_holder>(m, "WeaponSlotEnumArgument");
   py::class_<Megalo::OpcodeArgValueLoadoutPalette, Megalo::OpcodeArgValueEnumSuperclass, py::smart_holder>(m, "LoadoutPaletteArgument");
   py::class_<Megalo::OpcodeArgValueMappedControl, Megalo::OpcodeArgValueEnumSuperclass, py::smart_holder>(m, "MappedControlArgument", "MCC extension.");

   py::class_<Megalo::OpcodeArgValueFlagsSuperclass, Megalo::OpcodeArgValue, py::smart_holder>(m, "FlagsArgument")
      .def_readwrite("value", &Megalo::OpcodeArgValueFlagsSuperclass::value,
         "Raw bitmask -- use to_string()/decompile() for the resolved 'a | b | c' flag-name text.");
   py::class_<Megalo::OpcodeArgValueCreateObjectFlags, Megalo::OpcodeArgValueFlagsSuperclass, py::smart_holder>(m, "CreateObjectFlagsArgument");
   py::class_<Megalo::OpcodeArgValueKillerTypeFlags, Megalo::OpcodeArgValueFlagsSuperclass, py::smart_holder>(m, "KillerTypeFlagsArgument",
      "The flag set killer_type_is(guardians | suicide | ...) tests against.");
   py::class_<Megalo::OpcodeArgValuePlayerReqPurchaseModes, Megalo::OpcodeArgValueFlagsSuperclass, py::smart_holder>(m, "PlayerReqPurchaseModesArgument");

   py::class_<Megalo::OpcodeArgValueIconBase, Megalo::OpcodeArgValue, py::smart_holder>(m, "IconArgument")
      .def_readwrite("value", &Megalo::OpcodeArgValueIconBase::value, "-1 = none.");
   py::class_<Megalo::OpcodeArgValueEngineIcon, Megalo::OpcodeArgValueIconBase, py::smart_holder>(m, "EngineIconArgument");
   py::class_<Megalo::OpcodeArgValueHUDWidgetIcon, Megalo::OpcodeArgValueIconBase, py::smart_holder>(m, "HUDWidgetIconArgument");

   py::class_<Megalo::OpcodeArgValueForgeLabel, Megalo::OpcodeArgValue, py::smart_holder>(m, "ForgeLabelArgument")
      .def_property_readonly("value", [](Megalo::OpcodeArgValueForgeLabel& v) -> Megalo::ReachForgeLabel* { return v.value.operator->(); }, py::return_value_policy::reference_internal)
      .def("set_value", [](Megalo::OpcodeArgValueForgeLabel& v, GameVariantDataMultiplayer& mp, size_t label_index) {
            auto& label = index_into(mp.scriptContent.forgeLabels, label_index);
            v.value = &label;
         }, py::arg("mp"), py::arg("label_index"),
         "Points this argument (e.g. 'place_at_me's own 'label' argument) at mp.forgeLabels"
         "[label_index] -- same cobb::refcount_ptr<ReachForgeLabel> plain-pointer-assignment pattern "
         "as Trigger.forgeLabel/mark_trigger_forge_label() (value has no direct setter, same 'no "
         "setter on a refcount_ptr-backed property' gap as those, same fix).");
   py::class_<Megalo::OpcodeArgValuePlayerTraits, Megalo::OpcodeArgValue, py::smart_holder>(m, "PlayerTraitsArgument")
      .def_property_readonly("value", [](Megalo::OpcodeArgValuePlayerTraits& v) -> ReachMegaloPlayerTraits* { return v.value.operator->(); }, py::return_value_policy::reference_internal,
         "The referenced ScriptedPlayerTraits, or None.")
      .def("set_value", [](Megalo::OpcodeArgValuePlayerTraits& v, GameVariantDataMultiplayer& mp, size_t traits_index) {
            auto& traits = index_into(mp.scriptData.traits, traits_index);
            v.value = &traits;
         }, py::arg("mp"), py::arg("traits_index"),
         "Points this argument (e.g. apply_traits()'s own) at mp.scriptData.traits[traits_index] -- "
         "same cobb::refcount_ptr plain-pointer-assignment pattern as ForgeLabelArgument.set_value() "
         "(`value` has no direct setter, same reason). Raises IndexError if the variant has no such "
         "trait set; create one first with add_scripted_player_traits().");
   py::class_<Megalo::OpcodeArgValueWidget, Megalo::OpcodeArgValue, py::smart_holder>(m, "WidgetArgument")
      .def_property_readonly("value", [](Megalo::OpcodeArgValueWidget& v) -> Megalo::HUDWidgetDeclaration* { return v.value.operator->(); }, py::return_value_policy::reference_internal,
         "The referenced HUDWidgetDeclaration, or None.")
      .def("set_value", [](Megalo::OpcodeArgValueWidget& v, GameVariantDataMultiplayer& mp, size_t widget_index) {
            auto& widget = index_into(mp.scriptContent.widgets, widget_index);
            v.value = &widget;
         }, py::arg("mp"), py::arg("widget_index"),
         "Points this argument (e.g. set_text()'s own) at mp.scriptContent.widgets[widget_index] -- "
         "same pattern as ForgeLabelArgument.set_value(). Raises IndexError if the variant has no "
         "such widget; create one first with add_scripted_hud_widget().");

   py::class_<Megalo::OpcodeArgValuePlayerSet, Megalo::OpcodeArgValue, py::smart_holder>(m, "PlayerSetArgument")
      .def_property("set_type",
         [](const Megalo::OpcodeArgValuePlayerSet& p) { return p.set_type.value; },
         [](Megalo::OpcodeArgValuePlayerSet& p, Megalo::PlayerSetType v) { p.set_type.value = v; })
      .def_property_readonly("player", [](Megalo::OpcodeArgValuePlayerSet& p) -> Megalo::OpcodeArgValuePlayer& { return p.player; }, py::return_value_policy::reference_internal)
      .def_property_readonly("add_or_remove", [](Megalo::OpcodeArgValuePlayerSet& p) -> Megalo::OpcodeArgValueScalar& { return p.addOrRemove; }, py::return_value_policy::reference_internal);

   py::enum_<Megalo::PlayerSetType>(m, "PlayerSetType")
      .value("no_one", Megalo::PlayerSetType::no_one)
      .value("everyone", Megalo::PlayerSetType::everyone)
      .value("allies", Megalo::PlayerSetType::allies, "For teams.")
      .value("enemies", Megalo::PlayerSetType::enemies, "For teams.")
      .value("specific_player", Megalo::PlayerSetType::specific_player)
      .value("normal", Megalo::PlayerSetType::normal);

   py::enum_<Megalo::ShapeType>(m, "ShapeType")
      .value("none", Megalo::ShapeType::none)
      .value("sphere", Megalo::ShapeType::sphere)
      .value("cylinder", Megalo::ShapeType::cylinder)
      .value("box", Megalo::ShapeType::box);

   py::class_<Megalo::OpcodeArgValueShape, Megalo::OpcodeArgValue, py::smart_holder>(m, "ShapeArgument")
      .def_property("shape_type",
         [](const Megalo::OpcodeArgValueShape& s) { return s.shapeType.value; },
         [](Megalo::OpcodeArgValueShape& s, Megalo::ShapeType v) { s.shapeType.value = v; })
      .def_property_readonly("radius", [](Megalo::OpcodeArgValueShape& s) -> Megalo::OpcodeArgValueScalar& { return s.radius; }, py::return_value_policy::reference_internal, "Also used as 'width'.")
      .def_property_readonly("length", [](Megalo::OpcodeArgValueShape& s) -> Megalo::OpcodeArgValueScalar& { return s.length; }, py::return_value_policy::reference_internal)
      .def_property_readonly("top", [](Megalo::OpcodeArgValueShape& s) -> Megalo::OpcodeArgValueScalar& { return s.top; }, py::return_value_policy::reference_internal)
      .def_property_readonly("bottom", [](Megalo::OpcodeArgValueShape& s) -> Megalo::OpcodeArgValueScalar& { return s.bottom; }, py::return_value_policy::reference_internal)
      .def("axis", [](Megalo::OpcodeArgValueShape& s, uint8_t i) -> Megalo::OpcodeArgValueScalar& { return s.axis(i); }, py::return_value_policy::reference_internal,
         "radius/length/top/bottom by positional index instead of by name -- which ones are meaningful depends on shape_type.")
      .def_property_readonly("axis_count", &Megalo::OpcodeArgValueShape::axis_count);

   py::class_<Megalo::OpcodeArgValueWaypointIcon, Megalo::OpcodeArgValue, py::smart_holder>(m, "WaypointIconArgument")
      .def_readwrite("icon", &Megalo::OpcodeArgValueWaypointIcon::icon)
      .def_property_readonly("number", [](Megalo::OpcodeArgValueWaypointIcon& w) -> Megalo::OpcodeArgValueScalar& { return w.number; }, py::return_value_policy::reference_internal);

   py::enum_<Megalo::MeterType>(m, "MeterType")
      .value("none", Megalo::MeterType::none)
      .value("number", Megalo::MeterType::number)
      .value("timer", Megalo::MeterType::timer);

   py::class_<Megalo::OpcodeArgValueMeterParameters, Megalo::OpcodeArgValue, py::smart_holder>(m, "MeterParametersArgument")
      .def_property("type",
         [](const Megalo::OpcodeArgValueMeterParameters& mp) { return mp.type.value; },
         [](Megalo::OpcodeArgValueMeterParameters& mp, Megalo::MeterType v) { mp.type.value = v; })
      .def_property_readonly("timer", [](Megalo::OpcodeArgValueMeterParameters& mp) -> Megalo::OpcodeArgValueTimer& { return mp.timer; }, py::return_value_policy::reference_internal)
      .def_property_readonly("numerator", [](Megalo::OpcodeArgValueMeterParameters& mp) -> Megalo::OpcodeArgValueScalar& { return mp.numerator; }, py::return_value_policy::reference_internal)
      .def_property_readonly("denominator", [](Megalo::OpcodeArgValueMeterParameters& mp) -> Megalo::OpcodeArgValueScalar& { return mp.denominator; }, py::return_value_policy::reference_internal);

   py::class_<Megalo::OpcodeArgValueObjectTimerVariable, Megalo::OpcodeArgValue, py::smart_holder>(m, "ObjectTimerVariableArgument",
      "A timer variable index scoped to some object determined contextually (e.g. by another argument "
      "to the same opcode) -- NOT a Variable subclass despite the name, a lighter contextual reference.")
      .def_readwrite("base_scope", &Megalo::OpcodeArgValueObjectTimerVariable::baseScope)
      .def_readwrite("base_type", &Megalo::OpcodeArgValueObjectTimerVariable::baseType)
      .def_readwrite("index", &Megalo::OpcodeArgValueObjectTimerVariable::index, "-1 = none.")
      .def("is_none", &Megalo::OpcodeArgValueObjectTimerVariable::is_none);

   py::class_<Megalo::OpcodeArgValueObjectPlayerVariable, Megalo::OpcodeArgValue, py::smart_holder>(m, "ObjectPlayerVariableArgument",
      "An object variable plus the index of a player variable scoped to that object.")
      .def_property_readonly("object", [](Megalo::OpcodeArgValueObjectPlayerVariable& o) -> Megalo::OpcodeArgValueObject& { return o.object; }, py::return_value_policy::reference_internal)
      .def_readwrite("player_index", &Megalo::OpcodeArgValueObjectPlayerVariable::playerIndex, "-1 = none.");

   // ---- The two previously-deferred argument types (see AST.md's "Constructing new opcodes" ---
   // ---- and README's Roadmap item 3 for why they needed more than a mechanical field bind) ----

   py::enum_<Megalo::OpcodeStringTokenType>(m, "OpcodeStringTokenType")
      .value("none", Megalo::OpcodeStringTokenType::none)
      .value("player", Megalo::OpcodeStringTokenType::player, "Player's gamertag.")
      .value("team", Megalo::OpcodeStringTokenType::team, "\"team_none\" or a team designator string.")
      .value("object", Megalo::OpcodeStringTokenType::object, "\"none\" or \"unknown\".")
      .value("number", Megalo::OpcodeStringTokenType::number, "Rendered as \"%i\".")
      .value("timer", Megalo::OpcodeStringTokenType::timer, "Rendered as \"%i:%02i:%02i\"-style text.");

   py::class_<Megalo::OpcodeStringToken>(m, "OpcodeStringToken")
      .def_property("type",
         [](const Megalo::OpcodeStringToken& t) { return t.type.value; },
         [](Megalo::OpcodeStringToken& t, Megalo::OpcodeStringTokenType v) { t.type.value = v; })
      .def_property("value",
         [](const Megalo::OpcodeStringToken& t) -> Megalo::OpcodeArgValue* { return t.value; },
         [](Megalo::OpcodeStringToken& t, std::unique_ptr<Megalo::OpcodeArgValue> v) {
            if (t.value) delete t.value;
            t.value = v.release();
         },
         py::return_value_policy::reference_internal,
         "The argument this token inserts into the format string (a game-state value matching "
         "`type`, e.g. a ScalarVariable for `number`), or None if this slot is unused. Setting it "
         "deletes any previous value and takes ownership of the new one (from OpcodeArgTypeinfo."
         "create()/OpcodeArgValue.clone(), same ownership-transfer rules as Opcode.add_argument()).");

   py::class_<Megalo::OpcodeArgValueFormatString, Megalo::OpcodeArgValue, py::smart_holder>(m, "FormatStringArgument",
      "The `send_incident()`/`set_objective_text()`-style argument: a format string (with printf-"
      "style tokens like %s/%n) plus up to 2 further arguments (see `token(i)`) to insert into it.")
      .def_readonly("persistent", &Megalo::OpcodeArgValueFormatString::persistent)
      .def_property("string",
         [](Megalo::OpcodeArgValueFormatString& f) -> ReachString* { return f.string.operator->(); },
         [](Megalo::OpcodeArgValueFormatString& f, ReachString* s) { f.string = s; },
         py::return_value_policy::reference_internal,
         "The referenced string-table entry holding the format-string text itself, or None. "
         "Settable to any existing ReachString (e.g. one just added via ReachStringTable.add_new()) "
         "-- a plain reference-counted pointer assignment, no ownership-transfer ceremony needed "
         "(unlike the OpcodeArgValue*-owning fields elsewhere in this binding).")
      .def_readwrite("token_count", &Megalo::OpcodeArgValueFormatString::tokenCount,
         "How many of the (up to 2) token(i) slots are actually used.")
      .def("token", [](Megalo::OpcodeArgValueFormatString& f, size_t i) -> Megalo::OpcodeStringToken& {
            if (i >= Megalo::OpcodeArgValueFormatString::max_token_count)
               throw py::index_error(std::to_string(i));
            return f.tokens[i];
         }, py::return_value_policy::reference_internal,
         "One of up to max_token_count (2) fixed argument slots -- a raw C array on the C++ side, "
         "not a Python sequence (see README's 'Raw C arrays vs std::array' note), hence this index "
         "accessor rather than a bound list.")
      .def_readonly_static("max_token_count", &Megalo::OpcodeArgValueFormatString::max_token_count);

   py::class_<Megalo::OpcodeArgValueFormatStringPersistent, Megalo::OpcodeArgValueFormatString, py::smart_holder>(m, "FormatStringPersistentArgument");

   py::class_<Megalo::OpcodeArgValueMegaloScope, Megalo::OpcodeArgValue, py::smart_holder>(m, "MegaloScopeArgument",
      "MCC's 'Run Inline Trigger' (`begin ... end`) argument -- an inline opcode list embedded "
      "directly in this argument, as an alternative to `actionFunction_runNestedTrigger` pointing "
      "at a separate Trigger by index.")
      .def_property_readonly("data", [](Megalo::OpcodeArgValueMegaloScope& s) -> Megalo::CodeBlock& { return s.data; }, py::return_value_policy::reference_internal,
         "The inline trigger's own opcode list -- a second, argument-level CodeBlock distinct from "
         "Trigger. Use .data.opcode(i)/.opcode_count/.add_opcode() exactly like any other CodeBlock.");

   // ---- variable declarations (`declare global.number[0] with network priority high = 7`) ---------
   // Each scope (global/player/object/team) owns one VariableDeclarationSet: five lists (scalars,
   // timers, teams, players, objects) of VariableDeclaration, each list's length being how many
   // variables of that type the variant allocates in that scope. Native compile_script() rebuilds
   // all four sets from scratch out of the script text; these bindings are what let a from-scratch
   // compiler do the same without going through it.
   py::enum_<Megalo::variable_network_priority>(m, "VariableNetworkPriority")
      .value("local", Megalo::variable_network_priority::none)
      .value("low", Megalo::variable_network_priority::low)
      .value("high", Megalo::variable_network_priority::high);

   py::class_<Megalo::VariableDeclaration>(m, "VariableDeclaration")
      .def_property_readonly("type", &Megalo::VariableDeclaration::get_type)
      .def_property_readonly("has_network_type", &Megalo::VariableDeclaration::has_network_type,
         "False for a timer, which has no network priority.")
      .def_property_readonly("has_initial_value", &Megalo::VariableDeclaration::has_initial_value,
         "True for a number, timer or team; a player/object variable has no initial value.")
      .def_property("networking",
         [](const Megalo::VariableDeclaration& d) { return (Megalo::variable_network_priority)d.networking; },
         [](Megalo::VariableDeclaration& d, Megalo::variable_network_priority p) {
            if (!d.has_network_type())
               throw std::runtime_error("This type of variable has no network priority.");
            d.networking = p;
         })
      .def_property_readonly("initial_number", [](Megalo::VariableDeclaration& d) -> Megalo::OpcodeArgValueScalar* { return d.initial.number; },
         py::return_value_policy::reference_internal,
         "The initial value of a number or timer variable, as a ScalarVariable (retarget it with "
         "set_scope_by_format()/copy_from(), e.g. format '%i' for a constant). None for any other type.")
      .def_property("initial_team",
         [](const Megalo::VariableDeclaration& d) { return (int)(Megalo::const_team)d.initial.team; },
         [](Megalo::VariableDeclaration& d, int team) {
            if (d.get_type() != Megalo::variable_type::team)
               throw std::runtime_error("Only a team variable has an initial team.");
            if (team < (int)Megalo::const_team::none || team > (int)Megalo::const_team::neutral)
               throw py::value_error("Team must be -1 (no team), 0-7 (team 1-8) or 8 (neutral).");
            d.initial.team = (Megalo::const_team)team;
         },
         "-1 = no_team, 0-7 = team[0]-team[7], 8 = neutral_team.")
      .def("initial_is_default", &Megalo::VariableDeclaration::initial_value_is_default);

   py::class_<Megalo::VariableDeclarationSet>(m, "VariableDeclarationSet")
      .def("count", [](Megalo::VariableDeclarationSet& s, Megalo::variable_type t) {
            if (t == Megalo::variable_type::not_a_variable)
               throw py::value_error("Not a variable type.");
            return s.variables_by_type(t).size();
         })
      .def("get", [](Megalo::VariableDeclarationSet& s, Megalo::variable_type t, size_t i) -> Megalo::VariableDeclaration& {
            if (t == Megalo::variable_type::not_a_variable)
               throw py::value_error("Not a variable type.");
            auto& list = s.variables_by_type(t);
            if (i >= list.size())
               throw py::index_error(std::to_string(i));
            return *list[i];
         }, py::return_value_policy::reference_internal)
      .def("clear", [](Megalo::VariableDeclarationSet& s) {
            s.scalars.clear();
            s.timers.clear();
            s.teams.clear();
            s.players.clear();
            s.objects.clear();
         }, "Removes every declaration of every type.")
      .def("grow_to", [](Megalo::VariableDeclarationSet& s, Megalo::variable_type t, size_t count) {
            if (t == Megalo::variable_type::not_a_variable)
               throw py::value_error("Not a variable type.");
            auto& scope = Megalo::getScopeObjectForConstant(s.type);
            if (count > (size_t)scope.max_variables_of_type(t))
               throw py::index_error("This scope has room for only " + std::to_string(scope.max_variables_of_type(t)) + " variables of that type.");
            auto& list = s.variables_by_type(t);
            if (count > list.size())
               list.resize(count); // never shrinks (VariableDeclarationList::resize() leaks on shrink); use clear() for that
         }, py::arg("type"), py::arg("count"),
         "Grows this type's list to `count` default declarations (network priority low, initial "
         "value zero / no team). Does nothing if it is already at least that long. Raises "
         "IndexError past the scope's own maximum for the type.");

   py::class_<GameVariantDataMultiplayer>(m, "MultiplayerData")
      .def("variable_declarations", [](GameVariantDataMultiplayer& mp, Megalo::variable_scope scope) -> Megalo::VariableDeclarationSet& {
            auto& vars = mp.scriptContent.variables;
            switch (scope) {
               case Megalo::variable_scope::global: return vars.global;
               case Megalo::variable_scope::player: return vars.player;
               case Megalo::variable_scope::object: return vars.object;
               case Megalo::variable_scope::team:   return vars.team;
            }
            throw py::value_error("Only the global, player, object and team scopes have declarations.");
         }, py::return_value_policy::reference_internal)
      .def_readonly("options", &GameVariantDataMultiplayer::options) // not copy-assignable (contains ReachStringTable via team names)
      .def_readwrite("score_to_win", &GameVariantDataMultiplayer::scoreToWin)
      .def_readwrite("fireteams_enabled", &GameVariantDataMultiplayer::fireteamsEnabled)
      .def_readwrite("symmetric", &GameVariantDataMultiplayer::symmetric)
      .def_readwrite("map_permissions", &GameVariantDataMultiplayer::mapPermissions)
      .def_readwrite("player_rating_params", &GameVariantDataMultiplayer::playerRatingParams)
      .def_readwrite("title_update_data", &GameVariantDataMultiplayer::titleUpdateData)
      .def_readwrite("engine_icon", &GameVariantDataMultiplayer::engineIcon,
         "A SEPARATE copy from variant_header.engine_icon -- this direct field is the one "
         "page_multiplayer_metadata.cpp's updateFromVariant() actually reads back into the GUI's "
         "Metadata page combobox on load (RVT's own write handlers keep both, plus "
         "GameVariant.content_header's copy, in sync -- see mide.settings_writer for the Python "
         "equivalent). Writing only variant_header's copy is why an applied categorization_icon "
         "used to appear unchanged when reopening the file in RVT.")
      .def_readwrite("engine_category", &GameVariantDataMultiplayer::engineCategory,
         "See engine_icon's docstring -- the same duplicate-storage situation, for the 'Category' combobox.")
      .def_property_readonly("is_forge", [](GameVariantDataMultiplayer& mp) { return mp.isForge; })
      .def_property_readonly("variant_header", [](GameVariantDataMultiplayer& mp) -> ReachUGCHeader& { return mp.variantHeader; }, py::return_value_policy::reference_internal,
         "The real, GUI-facing Metadata page's data (title/description/engineIcon/engineCategory/author/editor). "
         "Read from here rather than GameVariant.content_header -- this copy is always big-endian; the chdr block's "
         "copy can be little-endian on old modded/360-era files (see refreshWindowTitle()'s comment in main_window.cpp).")
      .def_property_readonly("localized_name", [](GameVariantDataMultiplayer& mp) -> ReachStringTable& { return mp.localizedName; }, py::return_value_policy::reference_internal)
      .def_property_readonly("localized_desc", [](GameVariantDataMultiplayer& mp) -> ReachStringTable& { return mp.localizedDesc; }, py::return_value_policy::reference_internal)
      .def_property_readonly("localized_category", [](GameVariantDataMultiplayer& mp) -> ReachStringTable& { return mp.localizedCategory; }, py::return_value_policy::reference_internal)
      .def_property_readonly("script_strings", [](GameVariantDataMultiplayer& mp) -> ReachStringTable& { return mp.scriptData.strings; }, py::return_value_policy::reference_internal,
         "The big generic string table (up to 112 entries) that script-defined content -- Forge "
         "Label names, Scripted Option/Trait names and descriptions, etc. -- references by index. "
         "Distinct from localized_name/localized_desc/localized_category, which are their own "
         "small (usually 0-or-1-entry) tables.")
      .def("forge_label", [](GameVariantDataMultiplayer& mp, size_t i) -> Megalo::ReachForgeLabel& { return index_into(mp.scriptContent.forgeLabels, i); }, py::return_value_policy::reference_internal)
      .def_property_readonly("forge_label_count", [](GameVariantDataMultiplayer& mp) { return mp.scriptContent.forgeLabels.size(); })
      .def("scripted_option", [](GameVariantDataMultiplayer& mp, size_t i) -> ReachMegaloOption& { return index_into(mp.scriptData.options, i); }, py::return_value_policy::reference_internal)
      .def_property_readonly("scripted_option_count", [](GameVariantDataMultiplayer& mp) { return mp.scriptData.options.size(); })
      .def("scripted_player_trait", [](GameVariantDataMultiplayer& mp, size_t i) -> ReachMegaloPlayerTraits& { return index_into(mp.scriptData.traits, i); }, py::return_value_policy::reference_internal)
      .def_property_readonly("scripted_player_trait_count", [](GameVariantDataMultiplayer& mp) { return mp.scriptData.traits.size(); })
      .def("scripted_stat", [](GameVariantDataMultiplayer& mp, size_t i) -> ReachMegaloGameStat& { return index_into(mp.scriptContent.stats, i); }, py::return_value_policy::reference_internal)
      .def_property_readonly("scripted_stat_count", [](GameVariantDataMultiplayer& mp) { return mp.scriptContent.stats.size(); })
      .def("scripted_hud_widget", [](GameVariantDataMultiplayer& mp, size_t i) -> Megalo::HUDWidgetDeclaration& { return index_into(mp.scriptContent.widgets, i); }, py::return_value_policy::reference_internal)
      .def_property_readonly("scripted_hud_widget_count", [](GameVariantDataMultiplayer& mp) { return mp.scriptContent.widgets.size(); })
      // ---- growing the script-defined tables ----------------------------------------------------
      // Same as the RVT script editor's own "add" buttons (ui/script_editor/page_script_*.cpp): each
      // table is a cobb::indexed_list that owns its elements, so emplace_back() constructs and
      // appends one and no ownership transfer is needed (unlike Opcode/OpcodeArgValue construction).
      // Nothing else in this binding can create an entry, and native compile_script() doesn't either
      // (unlike forge labels, which it creates on first mention) -- it fails with "Index N is out of
      // bounds" -- so without these a variant can only ever use the widgets/traits/stats/options it
      // was loaded with.
      .def("add_scripted_option", [](GameVariantDataMultiplayer& mp) -> ReachMegaloOption& {
            auto* option = mp.create_script_option(); // engine's own: defaults name/desc/its first value too
            if (!option)
               throw std::runtime_error("Cannot add option: Limits::max_script_options (16) reached.");
            return *option;
         }, py::return_value_policy::reference_internal,
         "Appends a new scripted option (with its one required enum value, and its name/description "
         "defaulted to an empty string when one exists in script_strings) and returns it. Raises "
         "RuntimeError at the 16-option limit.")
      .def("add_scripted_player_traits", [](GameVariantDataMultiplayer& mp) -> ReachMegaloPlayerTraits& {
            auto& list = mp.scriptData.traits;
            if (list.size() >= list.max_count)
               throw std::runtime_error("Cannot add player traits: Limits::max_script_traits (16) reached.");
            auto* traits = list.emplace_back();
            traits->is_defined = true;
            if (auto* str = mp.scriptData.strings.get_empty_entry()) { // same default the script editor applies
               traits->name = str;
               traits->desc = str;
            }
            return *traits;
         }, py::return_value_policy::reference_internal,
         "Appends a new set of scripted player traits (name/description defaulted to an empty string "
         "when one exists in script_strings) and returns it. Raises RuntimeError at the 16-set limit.")
      .def("add_scripted_stat", [](GameVariantDataMultiplayer& mp) -> ReachMegaloGameStat& {
            auto& list = mp.scriptContent.stats;
            if (list.size() >= list.max_count)
               throw std::runtime_error("Cannot add stat: Limits::max_script_stats (4) reached.");
            auto* stat = list.emplace_back();
            stat->is_defined = true;
            if (auto* str = mp.scriptData.strings.get_empty_entry())
               stat->name = str;
            return *stat;
         }, py::return_value_policy::reference_internal,
         "Appends a new scripted stat (name defaulted to an empty string when one exists in "
         "script_strings) and returns it. Raises RuntimeError at the 4-stat limit.")
      .def("add_scripted_hud_widget", [](GameVariantDataMultiplayer& mp) -> Megalo::HUDWidgetDeclaration& {
            auto& list = mp.scriptContent.widgets;
            if (list.size() >= list.max_count)
               throw std::runtime_error("Cannot add HUD widget: Limits::max_script_widgets (4) reached.");
            auto* widget = list.emplace_back();
            widget->is_defined = true;
            return *widget;
         }, py::return_value_policy::reference_internal,
         "Appends a new scripted HUD widget and returns it. Raises RuntimeError at the 4-widget limit.")
      .def("trigger", [](GameVariantDataMultiplayer& mp, size_t i) -> Megalo::Trigger& { return index_into(mp.scriptContent.triggers, i); }, py::return_value_policy::reference_internal,
         "The real, compiled Megalo Trigger/Opcode/Condition/Action object graph (README.md Roadmap item 3, AST.md) -- "
         "not decompiled text. Each top-level trigger runs every tick unless entry_type marks it as event-bound "
         "(on_init/on_local_init/on_host_migration/on_object_death/local/pregame) or subroutine (called via a "
         "'run nested trigger' action, not run on its own).")
      .def_property_readonly("trigger_count", [](GameVariantDataMultiplayer& mp) { return mp.scriptContent.triggers.size(); })
      .def("add_trigger", [](GameVariantDataMultiplayer& mp) -> Megalo::Trigger& {
            auto* t = mp.scriptContent.triggers.emplace_back();
            if (!t)
               throw std::runtime_error("Cannot add trigger: Limits::max_triggers (320) reached.");
            return *t;
         }, py::return_value_policy::reference_internal,
         "A brand-new, blank Trigger (block_type/entry_type both default to 'normal') appended to "
         "scriptContent.triggers and returned by reference -- the indexed_list itself constructs and "
         "owns it (cobb::indexed_list::emplace_back()), unlike Opcode/OpcodeArgValue construction "
         "above, so there's no unique_ptr ownership-transfer step here. A fresh 'normal'/'normal' "
         "trigger already behaves as an always-ticking top-level trigger with no further wiring "
         "needed -- confirmed by compiling real top-level script text and checking the resulting "
         "Trigger objects, not assumed (see AST.md's 'Constructing a new Trigger' section). Populate "
         "it with add_opcode() same as any other CodeBlock/Trigger; call bind_trigger_as_event() "
         "instead if it should be event-bound (on_init/on_local_init/on_host_migration/"
         "on_object_death/local/pregame) rather than run every tick; leave entry_type as 'subroutine' "
         "if it should only run via another trigger's 'Run Nested Trigger' action pointing at it "
         "(TriggerArgument.value = the new trigger's index, i.e. trigger_count - 1 right after adding).")
      .def("clear_triggers", [](GameVariantDataMultiplayer& mp) {
            mp.scriptContent.triggers.clear();
            mp.scriptContent.entryPoints = Megalo::TriggerEntryPoints();
         },
         "Empties scriptContent.triggers and resets scriptContent.entryPoints back to 'no event "
         "bound' -- mirrors exactly what the native compiler itself does at the start of every "
         "compile_script() call (compiler.cpp: 'triggers.clear(); ... entryPoints = this->results."
         "events;'). A from-scratch compiler building triggers via add_trigger() must call this "
         "first, since add_trigger() otherwise appends onto whatever triggers the variant was loaded "
         "with rather than replacing them -- confirmed a real bug: recompiling a real, already-"
         "compiled gametype (loaded fresh, so still carrying its own previously-compiled triggers) "
         "without first clearing silently built a second, redundant copy of the whole script on top "
         "of the first instead of replacing it, hitting Limits::max_triggers (320) almost "
         "immediately even though the script's own construct set was otherwise fully supported.")
      .def("bind_trigger_as_event", [](GameVariantDataMultiplayer& mp, size_t trigger_index, Megalo::entry_type event) {
            auto& t = index_into(mp.scriptContent.triggers, trigger_index);
            t.entryType.value = event;
            mp.scriptContent.entryPoints.set_index_of_event(event, (int32_t)trigger_index);
         }, py::arg("trigger_index"), py::arg("event"),
         "Marks trigger_index as the handler for event (one of TriggerEntryType's on_init/"
         "on_local_init/on_host_migration/on_object_death/local/pregame -- 'normal'/'subroutine' do "
         "nothing here) -- sets BOTH the Trigger's own entry_type field AND the redundant "
         "entry_points lookup table together, atomically, rather than leaving the caller to "
         "remember both (see TriggerEntryPoints' own docstring for why both need to agree). Cannot "
         "express 'double host migration' -- see bind_trigger_as_double_host_migration_handler().")
      .def("bind_trigger_as_double_host_migration_handler", [](GameVariantDataMultiplayer& mp, size_t trigger_index) {
            auto& t = index_into(mp.scriptContent.triggers, trigger_index);
            t.entryType.value = Megalo::entry_type::on_host_migration;
            mp.scriptContent.entryPoints.indices.doubleHostMigrate = (int32_t)trigger_index;
         }, py::arg("trigger_index"),
         "'Double host migration' (the SECOND consecutive host migration in one match) has no "
         "dedicated TriggerEntryType member of its own -- confirmed directly (trigger.h's own "
         "entry_type enum comment: 'on_host_migration, // host migrations and double host "
         "migrations'): a trigger bound to EITHER event carries the exact same entry_type value, "
         "on_host_migration; the two are told apart purely by which of TriggerEntryPoints' own two "
         "separate index fields (indices.hostMigrate vs. indices.doubleHostMigrate, both real, "
         "already-serialized fields -- see trigger.cpp's own read()/write()) points at this "
         "trigger. bind_trigger_as_event()'s own single-enum-member switch (get_index_of_event()/"
         "set_index_of_event(), trigger.cpp) only ever reaches indices.hostMigrate for "
         "on_host_migration, so it structurally cannot set indices.doubleHostMigrate -- this sets "
         "both the shared entry_type field and specifically indices.doubleHostMigrate directly, "
         "atomically, same shape as bind_trigger_as_event() but for the one event type it can't "
         "reach.")
      .def("mark_trigger_as_subroutine", [](GameVariantDataMultiplayer& mp, size_t trigger_index) {
            auto& t = index_into(mp.scriptContent.triggers, trigger_index);
            t.entryType.value = Megalo::entry_type::subroutine;
         }, py::arg("trigger_index"),
         "Marks trigger_index as a subroutine -- only ever runs when reached via another trigger's "
         "'Run Nested Trigger' action (TriggerArgument.value = trigger_index), never independently "
         "each tick. entry_type has no direct setter (unlike block_type has none either) since every "
         "other transition goes through bind_trigger_as_event(), but 'subroutine' isn't an event type "
         "-- confirmed against compiler.cpp's own compiler behavior (Block::compile(), 'if (this->"
         "parent) { ... if (block->type != Type::root) t->entryType = entry_type::subroutine; }'): "
         "*every* nested if/do/for-each body the native compiler itself produces gets entry_type "
         "subroutine unconditionally, with no lookup-table counterpart to keep in sync (that's only "
         "needed for the event-bound entry types, see bind_trigger_as_event()) -- a plain field write "
         "here is the correct, complete operation, not a partial one.")
      .def("mark_trigger_block_type", [](GameVariantDataMultiplayer& mp, size_t trigger_index, Megalo::block_type type) {
            if (type == Megalo::block_type::for_each_object_with_label)
               throw std::invalid_argument("for_each_object_with_label needs a forge label wired up too -- use mark_trigger_forge_label() instead.");
            auto& t = index_into(mp.scriptContent.triggers, trigger_index);
            t.blockType.value = type;
         }, py::arg("trigger_index"), py::arg("type"),
         "Sets trigger_index's block_type (same 'no direct setter' gap as entry_type, same fix -- "
         "see mark_trigger_as_subroutine()). normal/for_each_player/for_each_player_randomly/"
         "for_each_team/for_each_object all need nothing else wired up beyond this field itself (the "
         "'current_player'/'current_object'/'current_team' the loop body then refers to are resolved "
         "contextually by the engine from block_type alone, not a stored variable this binding would "
         "need to set up separately) -- confirmed by compiling a real 'for each object do ... end' "
         "and inspecting the resulting Trigger before this binding was written.")
      .def("mark_trigger_forge_label", [](GameVariantDataMultiplayer& mp, size_t trigger_index, size_t label_index) {
            auto& t = index_into(mp.scriptContent.triggers, trigger_index);
            auto& label = index_into(mp.scriptContent.forgeLabels, label_index);
            t.blockType.value = Megalo::block_type::for_each_object_with_label;
            t.forgeLabel = &label;
         }, py::arg("trigger_index"), py::arg("label_index"),
         "Sets trigger_index's block_type to for_each_object_with_label AND wires its own forgeLabel "
         "(a cobb::refcount_ptr<ReachForgeLabel>, plain pointer assignment through its own operator=) "
         "to forgeLabels[label_index] together, atomically -- the same 'two fields need to agree' "
         "shape as bind_trigger_as_event()'s entry_type/entry_points pair, which is exactly why "
         "mark_trigger_block_type() refuses this one block_type on its own rather than leaving "
         "forge_label unset.")
      .def_property_readonly("entry_points", [](GameVariantDataMultiplayer& mp) -> Megalo::TriggerEntryPoints& { return mp.scriptContent.entryPoints; }, py::return_value_policy::reference_internal,
         "Direct access to the raw event->trigger-index table, for reading (e.g. 'which trigger "
         "handles on_init?') -- prefer bind_trigger_as_event() over writing through this directly.")
      .def_property("used_object_type_indices",
         [](GameVariantDataMultiplayer& mp) { return set_bit_indices(mp.scriptContent.usedMPObjectTypes); },
         [](GameVariantDataMultiplayer& mp, const std::vector<int>& indices) { set_bit_indices_from(mp.scriptContent.usedMPObjectTypes, indices); },
         "Set bit indices in scriptContent.usedMPObjectTypes (a 2048-bit flag list); no name list for object types is bound yet, so these are raw indices. "
         "Setting replaces the entire list (clear-then-set-each), matching how the other bit-list properties below work.")
      .def_property("engine_options_disabled",
         [](GameVariantDataMultiplayer& mp) { return set_bit_indices(mp.optionToggles.engine.disabled); },
         [](GameVariantDataMultiplayer& mp, const std::vector<int>& indices) { set_bit_indices_from(mp.optionToggles.engine.disabled, indices); },
         "Set bit indices in optionToggles.engine.disabled (a 1273-bit flag list, one per built-in engine option). "
         "Which index corresponds to which named option is not mapped anywhere in the bindings yet -- raw indices only.")
      .def_property("engine_options_hidden",
         [](GameVariantDataMultiplayer& mp) { return set_bit_indices(mp.optionToggles.engine.hidden); },
         [](GameVariantDataMultiplayer& mp, const std::vector<int>& indices) { set_bit_indices_from(mp.optionToggles.engine.hidden, indices); })
      .def_property("megalo_options_disabled",
         [](GameVariantDataMultiplayer& mp) { return set_bit_indices(mp.optionToggles.megalo.disabled); },
         [](GameVariantDataMultiplayer& mp, const std::vector<int>& indices) { set_bit_indices_from(mp.optionToggles.megalo.disabled, indices); },
         "Set bit indices in optionToggles.megalo.disabled (a 16-bit flag list, one per script-defined option -- "
         "i.e. indexes into scriptData.options, see scripted_option()/scripted_option_count).")
      .def_property("megalo_options_hidden",
         [](GameVariantDataMultiplayer& mp) { return set_bit_indices(mp.optionToggles.megalo.hidden); },
         [](GameVariantDataMultiplayer& mp, const std::vector<int>& indices) { set_bit_indices_from(mp.optionToggles.megalo.hidden, indices); })
      .def("compile_script", &compile_script, py::arg("source"), py::arg("create_unresolved_strings") = true,
         "Compile Megalo source text and, on success, apply it to this variant's script content "
         "(triggers/conditions/actions, string table entries for new string literals, etc).")
      .def("get_full_size_data", &get_full_size_data,
         "Space usage (bits per section) and entry counts (triggers/conditions/actions/...), "
         "matching what the Script and Data Editor's bottom pane shows -- unlike the C++-only "
         "get_size_data(), this also fills in script_content bits and the trigger/condition/"
         "action counts (see update_script_from()).");

   py::class_<GameVariant>(m, "GameVariant")
      .def(py::init<>())
      .def_property_readonly("multiplayer", &GameVariant::get_multiplayer_data, py::return_value_policy::reference_internal,
         "The multiplayer/Forge data, or None if this is not a multiplayer/Forge variant.")
      .def_property_readonly("firefight", &GameVariant::get_firefight_data, py::return_value_policy::reference_internal,
         "The Firefight data, or None if this is not a Firefight variant.")
      .def_property_readonly("content_header", [](GameVariant& v) -> ReachUGCHeader& { return v.contentHeader.data; }, py::return_value_policy::reference_internal,
         "The chdr block's own title/description/author copy. Prefer MultiplayerData.variant_header "
         "when the variant is multiplayer/Forge (see that property's docstring); this is the fallback "
         "for variant types that don't have their own header copy (e.g. Firefight).")
      .def("decompile_script", &decompile_variant, "Decompile this variant's Megalo script back to source text.")
      .def("save", &save_variant, py::arg("path"),
         "Write the variant to disk at `path` (any path -- doesn't have to be where it was loaded from).");
}
