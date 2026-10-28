"""Direct multi-unit root symbols retain physical identity and explicit model mappings."""
import pytest

from yasdl import Block, Package, PackageType, SpiceModel, netlist, spice_netlist, std
from yasdl.kicad_lib import BUNDLED_MODELS, KICAD_CLI

MODEL = SpiceModel('X', ('3', '2', '1', '5', '6', '7', '8', '4'),
                   'yasdl_ideal_opamp_dual', library=str(BUNDLED_MODELS))

def design(chip):
    return Block('RootPackage', '[VCC]\n  │\n  PW\n  │\n[VEE]\n\n{a}──FA──FB──{b}',
                 PW=chip.power(), FA=std.follower(chip.unit(1)), FB=std.follower(chip.unit('b')))

def test_root_package_type_preserves_units_and_complete_whole_model():
    chip = PackageType('Device:Opamp_Dual', 'DUAL', MODEL)(name='UA')
    assert chip.unit(1) is chip.unit('A') and chip.unit('C') is chip.power()
    nets = netlist(design(chip))
    assert nets['a'] == ['FA.U1.3']
    assert nets['VCC'] == ['PW.8'] and nets['VEE'] == ['PW.4']
    text = spice_netlist(design(chip))
    assert text.count('X_UA ') == 1 and 'yasdl_ideal_opamp_dual' in text


@pytest.mark.integration
@pytest.mark.skipif(not KICAD_CLI.exists(), reason='kicad-cli missing')
def test_raw_package_physical_export_and_spice(tmp_path):
    from yasdl.kicad_export import render
    from yasdl.kicad_sch import export_netlist_full
    chip = Package('Device:Opamp_Dual', name='UA', value='DUAL', spice=MODEL,
                   footprint='Package_DIP:DIP-8_W7.62mm')
    result = render(design(chip), tmp_path, svg=False, spice=True)
    assert result['roundtrip_ok'] and result['spice_ok'] and result['erc'] == [], result
    nets, components = export_netlist_full(result['schematic'])
    assert components['U1']['footprint'] == 'Package_DIP:DIP-8_W7.62mm'
    assert ('U1', '3') in nets['/a'] and ('U1', '7') in nets['/b']


@pytest.mark.integration
@pytest.mark.skipif(not KICAD_CLI.exists(), reason='kicad-cli missing')
def test_physical_package_needs_no_simulation_resources(tmp_path):
    from yasdl.kicad_export import render
    missing = SpiceModel('X', MODEL.pins, 'absent', library=str(tmp_path / 'absent.lib'))
    chip = PackageType('Device:Opamp_Dual', 'PHYSICAL', missing, sim=False)()
    text = spice_netlist(design(chip))
    assert '.include' not in text and 'X_' not in text
    result = render(design(chip), tmp_path, svg=False, spice=True)
    assert result['roundtrip_ok'] and result['spice_ok'] and result['erc'] == [], result


@pytest.mark.integration
@pytest.mark.skipif(not KICAD_CLI.exists(), reason='kicad-cli missing')
def test_package_preserves_supplied_model_pin_mapping_and_rejects_a_swap(tmp_path):
    from dataclasses import replace
    from yasdl.kicad_export import render
    # Independent order of the model header: inpa, inna, outa, inpb, innb, outb, vcc, vee.
    pins = '3=inpa 2=inna 1=outa 5=inpb 6=innb 7=outb 8=vcc 4=vee'
    mapping = replace(MODEL, sim_pins=pins)
    correct = PackageType('Device:Opamp_Dual', 'MAPPED', mapping)('UA')
    info = render(design(correct), tmp_path / 'correct', svg=False, spice=True)
    assert info['spice_ok'] and pins in info['schematic'].read_text()
    incorrect = PackageType('Device:Opamp_Dual', 'MAPPED', replace(mapping, sim_pins=pins.replace('3=inpa 2=inna', '3=inna 2=inpa')))('UA')
    result = render(design(incorrect), tmp_path / 'incorrect', svg=False, spice=True)
    assert result['roundtrip_ok'] and not result['spice_ok']


@pytest.mark.integration
@pytest.mark.skipif(not KICAD_CLI.exists(), reason='kicad-cli missing')
def test_package_model_resource_can_be_supplied_at_render_time(tmp_path):
    from dataclasses import replace
    from yasdl.kicad_export import render
    chip = PackageType('Device:Opamp_Dual', 'EXTERNAL_MODEL', replace(MODEL, library=None))('UA')
    result = render(design(chip), tmp_path, svg=False, spice=True, spice_libs=(BUNDLED_MODELS,))
    assert result['roundtrip_ok'] and result['spice_ok'] and result['erc'] == [], result


@pytest.mark.integration
@pytest.mark.skipif(not KICAD_CLI.exists(), reason='kicad-cli missing')
def test_per_channel_package_model_can_be_supplied_at_render_time(tmp_path):
    from yasdl.kicad_export import render
    from yasdl.parts import dual_opamp
    descriptor = dual_opamp('RENDER_MODEL_DUAL', model='yasdl_ideal_opamp5')
    chip = descriptor('UA')
    # Named views use the same public interface as the direct root-symbol package.
    block = Block('SuppliedUnitModel', '[VCC]\n  │\n  PW\n  │\n[VEE]\n\n{a}──FA──FB──{b}',
                  PW=chip.power(), FA=std.follower(chip.unit('A')), FB=std.follower(chip.unit('B')))
    result = render(block, tmp_path, svg=False, spice=True, spice_libs=(BUNDLED_MODELS,))
    assert result['roundtrip_ok'] and result['spice_ok'] and result['erc'] == [], result
