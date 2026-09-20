#pragma once
//
// Generic pybind11 type_casters for this project's bit-packed field wrappers, so that
// ordinary `.def_readwrite("field", &Cls::field)` works directly on them from Python
// as plain ints/bools, without hand-writing a getter/setter lambda per field.
//
// Fields declared as `cobb::bitnumber<N, T, ...>` (including the `cobb::bytenumber<T>`
// alias) round-trip through their `underlying_int` type -- this covers both plain integer
// fields and fields whose underlying type is a scoped enum (e.g. `reach::weapon`), since
// none of those ~50 `reach::` enums are individually registered with pybind11 here. Python
// sees and sets these as plain ints; the enum values documented in the C++ headers
// (game_variants/components/*.h, game_variants/types/multiplayer.h) are the reference for
// what a given int means for a given field.
//
// `cobb::bitbool` fields round-trip as Python bool.
//
#include <pybind11/pybind11.h>
#include <QString>
#include "helpers/bitnumber.h"

namespace pybind11 { namespace detail {

   template <int bitcount, typename underlying, bool offset, typename presence_bit, underlying if_absent>
   struct type_caster<cobb::bitnumber<bitcount, underlying, offset, presence_bit, if_absent>> {
      using value_type = cobb::bitnumber<bitcount, underlying, offset, presence_bit, if_absent>;
      using int_type    = typename value_type::underlying_int;
      using int_caster  = make_caster<int_type>;

      PYBIND11_TYPE_CASTER(value_type, const_name("int"));

      bool load(handle src, bool convert) {
         int_caster caster;
         if (!caster.load(src, convert))
            return false;
         value.value = static_cast<underlying>(cast_op<int_type>(std::move(caster)));
         return true;
      }

      static handle cast(const value_type& src, return_value_policy policy, handle parent) {
         return int_caster::cast(static_cast<int_type>(src.value), policy, parent);
      }
   };

   template <>
   struct type_caster<cobb::bitbool> {
      PYBIND11_TYPE_CASTER(cobb::bitbool, const_name("bool"));

      bool load(handle src, bool convert) {
         make_caster<bool> caster;
         if (!caster.load(src, convert))
            return false;
         value.value = cast_op<bool>(std::move(caster));
         return true;
      }

      static handle cast(const cobb::bitbool& src, return_value_policy, handle) {
         return pybind11::bool_(src.value).release();
      }
   };

   template <>
   struct type_caster<QString> {
      PYBIND11_TYPE_CASTER(QString, const_name("str"));

      bool load(handle src, bool convert) {
         make_caster<std::string> caster;
         if (!caster.load(src, convert))
            return false;
         value = QString::fromUtf8(cast_op<std::string>(std::move(caster)).c_str());
         return true;
      }

      static handle cast(const QString& src, return_value_policy, handle) {
         auto utf8 = src.toUtf8();
         return PyUnicode_FromStringAndSize(utf8.constData(), utf8.size());
      }
   };

}} // namespace pybind11::detail
