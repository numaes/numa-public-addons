from odoo.addons.base.tests.common import SavepointCase
from ..models import miniqweb
import logging
_logger = logging.getLogger(__name__)


class TestMiniQweb(SavepointCase):
    """ Test running at-install to test flows independently to other modules """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def test_non_dynamic_content(self):
        result = miniqweb.render('''
        <data>
            <p>Esta es una prueba</p>
            <div>
                <span>Para ver como sale</span>
            </div>
        </data>            
        ''')
        self.assertTrue(result == '''<data>
            <p>Esta es una prueba</p>
            <div>
                <span>Para ver como sale</span>
            </div>
        </data>''', 'Test non dynamic content')

    def test_basic_parameters_sustitution(self):
        result = miniqweb.render('''
        <div>
            <span t-esc="a"/>
            <div>
                <span t-esc="b"/>
            </div>
        </div>            
        ''', a=1, b=2)
        self.assertTrue(result == '''<div>
            <span>1</span>
            <div>
                <span>2</span>
            </div>
        </div>''', 'Test basic parameters sustitution')

    def test_basic_foreach(self):
        result = miniqweb.render('''
        <div>
            <t t-foreach="[1,2,3]" t-as="l">
                <span t-esc="l"/>
            </t>
        </div>
        ''')
        self.assertTrue(result == '''<div>
            <span>1</span>
            <span>2</span>
            <span>3</span>
            </div>''', 'Test basic foreach')

    def test_basic_while(self):
        result = miniqweb.render('''
        <div>
            <t t-set="a" t-value="2"/>
            <t t-while="a > 0">
                <span t-esc="a"/>
                <t t-set="a" t-value="a-1"/>
            </t>
        </div>
        ''')
        self.assertTrue(result == '''<div>
            <span>2</span>
                <span>1</span>
                </div>''', 'Test basic while')

    def test_if(self):
        result = miniqweb.render('''
        <div>
            <span t-if="a == 1" t-esc="'Vale uno'"/>
            <span t-if="a == 2" t-esc="'Vale dos'"/>
            <span t-if="a != 1" t-esc="'NO vale uno'"/>
            <span t-if="a != 2" t-esc="'NO vale dos'"/>
        </div>
        ''', a=1)
        self.assertTrue(result == '''<div>
            <span>Vale uno</span>
            <span>NO vale dos</span>
        </div>''', 'Test if')

    def test_format(self):
        result = miniqweb.render('''
        <div>
            <span t-attf-value="esta es una prueba de {a} y {b}" />
        </div>
        ''', a=1, b=2)
        self.assertTrue(result == '''<div>
            <span value="esta es una prueba de 1 y 2"/>
        </div>''', 'Test format')

    def test_esc(self):
        result = miniqweb.render('''
        <div>
            <span t-esc="'esta es una prueba de esc'" />
        </div>
        ''')
        self.assertTrue(result == '''<div>
            <span>esta es una prueba de esc</span>
        </div>''', 'Test esc')

    def test_esc_escaped_chars(self):
        result = miniqweb.render('''
        <div>
            <span t-esc="text" />
        </div>
        ''', text='esta <es> una prueba de esc')
        self.assertTrue(result == '''<div>
            <span>esta &lt;es&gt; una prueba de esc</span>
        </div>''', 'Test esc, escaped chars')

    def test_raw(self):
        result = miniqweb.render('''
        <div>
            <span t-raw="text" />
        </div>
        ''', text='esta <span>es una prueba</span> de raw')
        self.assertTrue(result == """<div>
            <span>esta <span>es una prueba</span> de raw</span>
        </div>""", 'Test raw')


