// VJ Chaser - FFGL effect for Resolume
// Masks the input to the Advanced Output slices that are active in the current step.
// Steps advance on Resolume's BPM. Data comes from %APPDATA%\VJChaser\chaser.vjc (written by VJ Chaser Editor).

#include <FFGLSDK.h>
#include <string>
#include <vector>
#include <fstream>
#include <sstream>
#include <cmath>
#include <cstdlib>
#include <sys/stat.h>

using namespace ffglex;

static const int MAX_SLICES = 1024;

enum Params : FFUInt32
{
	P_SEQUENCE,
	P_STEPLEN,
	P_DIRECTION,
	P_MODE,
	P_FADE,
	P_INVERT,
	P_OFFSET,
	P_RELOAD,
	P_COUNT
};

static const float kStepBeats[] = { 0.25f, 0.5f, 1.0f, 2.0f, 4.0f, 8.0f, 16.0f };
static const char* kStepNames[] = { "1/16", "1/8", "1/4 (Beat)", "1/2", "1 Bar", "2 Bars", "4 Bars" };

struct Sequence
{
	std::string name;
	std::vector< std::vector< int > > steps;
};

class VJChaser : public CFFGLPlugin
{
public:
	VJChaser();
	FFResult InitGL( const FFGLViewportStruct* vp ) override;
	FFResult ProcessOpenGL( ProcessOpenGLStruct* pGL ) override;
	FFResult DeInitGL() override;
	FFResult SetFloatParameter( unsigned int index, float value ) override;
	float GetFloatParameter( unsigned int index ) override;

private:
	void LoadData( bool force );
	std::string DataPath() const;
	int CurrentStep( int nSteps, double beatPos );

	FFGLShader shader;
	FFGLScreenQuad quad;
	GLuint dataTex = 0;

	// params
	float pSequence = 1, pStepLen = 2, pDirection = 0, pMode = 0, pFade = 0, pInvert = 0, pOffset = 0;

	// data
	std::vector< float > quads;      // 8 floats per slice (gl coords, y up, 0..1)
	std::vector< Sequence > seqs;
	std::vector< float > level;      // per-slice intensity (for fade)
	long long fileStamp = -1;
	int frameCounter = 0;

	// timing
	float lastBarPhase = 0.f;
	double barCount = 0;
	double lastTime = -1;
	double freeBeats = 0;
};

static CFFGLPluginInfo PluginInfo(
	PluginFactory< VJChaser >,
	"VJCH",
	"VJ Chaser",
	2, 1,
	1, 0,
	FF_EFFECT,
	"Chase Advanced Output slices on the beat",
	"VJ Chaser by VJ Samir" );

static const char vsCode[] = R"(#version 410 core
uniform vec2 MaxUV;
layout( location = 0 ) in vec4 vPosition;
layout( location = 1 ) in vec2 vUV;
out vec2 uv;
out vec2 pos;
void main()
{
	gl_Position = vPosition;
	uv  = vUV * MaxUV;
	pos = vUV;
}
)";

static const char fsCode[] = R"(#version 410 core
uniform sampler2D InputTexture;
uniform sampler2D DataTex;
uniform int Count;
uniform int Mode;
uniform float Invert;
in vec2 uv;
in vec2 pos;
out vec4 fragColor;

float cross2( vec2 a, vec2 b ) { return a.x * b.y - a.y * b.x; }

float insideQuad( vec2 p, vec2 a, vec2 b, vec2 c, vec2 d )
{
	float s1 = cross2( b - a, p - a );
	float s2 = cross2( c - b, p - b );
	float s3 = cross2( d - c, p - c );
	float s4 = cross2( a - d, p - d );
	bool neg = s1 < 0.0 || s2 < 0.0 || s3 < 0.0 || s4 < 0.0;
	bool posi = s1 > 0.0 || s2 > 0.0 || s3 > 0.0 || s4 > 0.0;
	return ( neg && posi ) ? 0.0 : 1.0;
}

void main()
{
	float m = 0.0;
	for( int i = 0; i < Count; i++ )
	{
		float lv = texelFetch( DataTex, ivec2( i, 2 ), 0 ).r;
		if( lv <= 0.001 ) continue;
		vec4 ab = texelFetch( DataTex, ivec2( i, 0 ), 0 );
		vec4 cd = texelFetch( DataTex, ivec2( i, 1 ), 0 );
		m = max( m, lv * insideQuad( pos, ab.xy, ab.zw, cd.xy, cd.zw ) );
	}
	m = mix( m, 1.0 - m, Invert );
	vec4 col = texture( InputTexture, uv );
	if( Mode == 1 )      fragColor = vec4( vec3( m ), m );          // white chase only
	else if( Mode == 2 ) fragColor = col + vec4( vec3( m ), m );    // add white flash on top of video
	else                 fragColor = col * m;                        // mask the video
	fragColor = clamp( fragColor, vec4( 0.0 ), vec4( 1.0 ) );
	fragColor.rgb = min( fragColor.rgb, vec3( fragColor.a ) );     // keep premultiplied
}
)";

VJChaser::VJChaser()
{
	SetMinInputs( 1 );
	SetMaxInputs( 1 );

	SetParamInfo( P_SEQUENCE, "Sequence", FF_TYPE_INTEGER, 1.0f );
	SetParamRange( P_SEQUENCE, 1.0f, 64.0f );

	SetOptionParamInfo( P_STEPLEN, "Step Length", 7, 2.0f );
	for( unsigned int i = 0; i < 7; i++ )
		SetParamElementInfo( P_STEPLEN, i, kStepNames[ i ], (float)i );

	SetOptionParamInfo( P_DIRECTION, "Direction", 4, 0.0f );
	SetParamElementInfo( P_DIRECTION, 0, "Forward", 0.0f );
	SetParamElementInfo( P_DIRECTION, 1, "Reverse", 1.0f );
	SetParamElementInfo( P_DIRECTION, 2, "Ping Pong", 2.0f );
	SetParamElementInfo( P_DIRECTION, 3, "Random", 3.0f );

	SetOptionParamInfo( P_MODE, "Mode", 3, 0.0f );
	SetParamElementInfo( P_MODE, 0, "Mask Video", 0.0f );
	SetParamElementInfo( P_MODE, 1, "White Chase", 1.0f );
	SetParamElementInfo( P_MODE, 2, "Add Flash", 2.0f );

	SetParamInfo( P_FADE, "Fade", FF_TYPE_STANDARD, 0.0f );
	SetParamInfo( P_INVERT, "Invert", FF_TYPE_BOOLEAN, false );
	SetParamInfo( P_OFFSET, "Step Offset", FF_TYPE_INTEGER, 0.0f );
	SetParamRange( P_OFFSET, 0.0f, 63.0f );
	SetParamInfo( P_RELOAD, "Reload", FF_TYPE_EVENT, false );

	level.assign( MAX_SLICES, 0.0f );
}

std::string VJChaser::DataPath() const
{
	const char* app = std::getenv( "APPDATA" );
	std::string base = app ? std::string( app ) : std::string( "." );
	return base + "\\VJChaser\\chaser.vjc";
}

void VJChaser::LoadData( bool force )
{
	std::string path = DataPath();
#ifdef _WIN32
	struct _stat64 st;
	if( _stat64( path.c_str(), &st ) != 0 )
#else
	struct stat st;
	if( stat( path.c_str(), &st ) != 0 )
#endif
	{
		if( force ) FFGLLog::LogToHost( "VJ Chaser: no data file yet, open VJ Chaser Editor and save" );
		return;
	}
	long long stamp = (long long)st.st_mtime * 1000 + (long long)st.st_size;
	if( !force && stamp == fileStamp )
		return;

	std::ifstream f( path );
	if( !f.good() )
		return;

	std::vector< float > newQuads;
	std::vector< Sequence > newSeqs;
	std::string line;
	std::string head;
	if( !std::getline( f, head ) || head.rfind( "VJC", 0 ) != 0 )
		return;

	while( std::getline( f, line ) )
	{
		if( line.empty() ) continue;
		std::istringstream ls( line );
		std::string tag;
		ls >> tag;
		if( tag == "S" )
		{
			int n = 0;
			ls >> n;
			for( int i = 0; i < n && std::getline( f, line ); i++ )
			{
				std::istringstream q( line );
				float v[ 8 ] = { 0 };
				for( int k = 0; k < 8; k++ ) q >> v[ k ];
				if( (int)newQuads.size() / 8 >= MAX_SLICES ) continue;
				for( int k = 0; k < 4; k++ )
				{
					newQuads.push_back( v[ k * 2 ] );               // x
					newQuads.push_back( 1.0f - v[ k * 2 + 1 ] );    // y flipped to GL
				}
			}
		}
		else if( tag == "N" )
		{
			Sequence s;
			std::getline( ls >> std::ws, s.name );
			newSeqs.push_back( s );
		}
		else if( tag == "T" && !newSeqs.empty() )
		{
			int n = 0;
			ls >> n;
			for( int i = 0; i < n && std::getline( f, line ); i++ )
			{
				std::istringstream q( line );
				int k = 0;
				q >> k;
				std::vector< int > step;
				for( int j = 0; j < k; j++ )
				{
					int idx;
					if( q >> idx ) step.push_back( idx );
				}
				newSeqs.back().steps.push_back( step );
			}
		}
	}
	quads    = newQuads;
	seqs     = newSeqs;
	fileStamp = stamp;
	std::string msg = "VJ Chaser: loaded " + std::to_string( quads.size() / 8 ) + " slices, " + std::to_string( seqs.size() ) + " sequences";
	FFGLLog::LogToHost( msg.c_str() );
}

FFResult VJChaser::InitGL( const FFGLViewportStruct* vp )
{
	if( !shader.Compile( vsCode, fsCode ) )
	{
		DeInitGL();
		return FF_FAIL;
	}
	if( !quad.Initialise() )
	{
		DeInitGL();
		return FF_FAIL;
	}
	glGenTextures( 1, &dataTex );
	{
		Scoped2DTextureBinding bind( dataTex );
		glTexParameteri( GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST );
		glTexParameteri( GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST );
		glTexParameteri( GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE );
		glTexParameteri( GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE );
		glTexImage2D( GL_TEXTURE_2D, 0, GL_RGBA32F, MAX_SLICES, 3, 0, GL_RGBA, GL_FLOAT, nullptr );
	}
	LoadData( true );
	return CFFGLPlugin::InitGL( vp );
}

int VJChaser::CurrentStep( int n, double beatPos )
{
	if( n <= 0 ) return 0;
	int li = (int)pStepLen;
	if( li < 0 ) li = 0;
	if( li > 6 ) li = 6;
	long long step = (long long)std::floor( beatPos / kStepBeats[ li ] ) + (long long)pOffset;
	if( step < 0 ) step = 0;
	int dir = (int)( pDirection + 0.5f );
	if( dir == 1 ) return n - 1 - (int)( step % n );
	if( dir == 2 )
	{
		if( n == 1 ) return 0;
		int period = 2 * n - 2;
		int p = (int)( step % period );
		return p < n ? p : period - p;
	}
	if( dir == 3 )
	{
		unsigned long long h = (unsigned long long)step * 2654435761ULL;
		h ^= h >> 13;
		h *= 0x5bd1e995ULL;
		h ^= h >> 15;
		return (int)( h % (unsigned long long)n );
	}
	return (int)( step % n );
}

FFResult VJChaser::ProcessOpenGL( ProcessOpenGLStruct* pGL )
{
	if( pGL->numInputTextures < 1 || pGL->inputTextures[ 0 ] == NULL )
		return FF_FAIL;

	if( ++frameCounter >= 30 )
	{
		frameCounter = 0;
		LoadData( false );
	}

	// ---- beat position
	double now = hostTime;   // ms
	double dt  = ( lastTime < 0 ) ? 0.0 : ( now - lastTime ) / 1000.0;
	if( dt < 0 || dt > 1.0 ) dt = 0;
	lastTime = now;

	double beatPos;
	if( bpm > 1.0f )
	{
		if( barPhase + 0.5f < lastBarPhase ) barCount += 1.0;
		lastBarPhase = barPhase;
		beatPos      = ( barCount + barPhase ) * 4.0;
	}
	else
	{
		freeBeats += dt * 2.0;   // 120 bpm fallback
		beatPos = freeBeats;
	}

	// ---- active slices for this step
	int nSlices = (int)quads.size() / 8;
	std::vector< char > active( nSlices, 0 );
	int si = (int)pSequence - 1;
	double stepSec = 0.5;
	if( si >= 0 && si < (int)seqs.size() && !seqs[ si ].steps.empty() )
	{
		const Sequence& s = seqs[ si ];
		int st = CurrentStep( (int)s.steps.size(), beatPos );
		for( int idx : s.steps[ st ] )
			if( idx >= 0 && idx < nSlices ) active[ idx ] = 1;
		int li = (int)pStepLen;
		if( li < 0 ) li = 0;
		if( li > 6 ) li = 6;
		stepSec = kStepBeats[ li ] * 60.0 / ( bpm > 1.0f ? bpm : 120.0 );
	}

	// ---- fade / levels
	double tau = pFade * stepSec * 3.0;
	float decay = ( tau > 0.0001 ) ? (float)std::exp( -dt / tau ) : 0.0f;
	std::vector< float > data( (size_t)MAX_SLICES * 12, 0.0f );
	for( int i = 0; i < nSlices; i++ )
	{
		if( active[ i ] ) level[ i ] = 1.0f;
		else level[ i ] *= decay;
		const float* q = &quads[ (size_t)i * 8 ];
		float* r0 = &data[ (size_t)i * 4 ];
		float* r1 = &data[ ( (size_t)MAX_SLICES + i ) * 4 ];
		float* r2 = &data[ ( (size_t)MAX_SLICES * 2 + i ) * 4 ];
		r0[ 0 ] = q[ 0 ]; r0[ 1 ] = q[ 1 ]; r0[ 2 ] = q[ 2 ]; r0[ 3 ] = q[ 3 ];
		r1[ 0 ] = q[ 4 ]; r1[ 1 ] = q[ 5 ]; r1[ 2 ] = q[ 6 ]; r1[ 3 ] = q[ 7 ];
		r2[ 0 ] = level[ i ];
	}

	ScopedShaderBinding shaderBinding( shader.GetGLID() );

	ScopedSamplerActivation act1( 1 );
	Scoped2DTextureBinding dataBinding( dataTex );
	glTexSubImage2D( GL_TEXTURE_2D, 0, 0, 0, MAX_SLICES, 3, GL_RGBA, GL_FLOAT, data.data() );

	ScopedSamplerActivation act0( 0 );
	Scoped2DTextureBinding inputBinding( pGL->inputTextures[ 0 ]->Handle );

	shader.Set( "InputTexture", 0 );
	shader.Set( "DataTex", 1 );
	FFGLTexCoords maxCoords = GetMaxGLTexCoords( *pGL->inputTextures[ 0 ] );
	shader.Set( "MaxUV", maxCoords.s, maxCoords.t );
	glUniform1i( shader.FindUniform( "Count" ), nSlices );
	glUniform1i( shader.FindUniform( "Mode" ), (int)( pMode + 0.5f ) );
	glUniform1f( shader.FindUniform( "Invert" ), pInvert > 0.5f ? 1.0f : 0.0f );

	quad.Draw();
	return FF_SUCCESS;
}

FFResult VJChaser::DeInitGL()
{
	shader.FreeGLResources();
	quad.Release();
	if( dataTex )
	{
		glDeleteTextures( 1, &dataTex );
		dataTex = 0;
	}
	return FF_SUCCESS;
}

FFResult VJChaser::SetFloatParameter( unsigned int index, float value )
{
	switch( index )
	{
	case P_SEQUENCE:  pSequence = value; break;
	case P_STEPLEN:   pStepLen = value; break;
	case P_DIRECTION: pDirection = value; break;
	case P_MODE:      pMode = value; break;
	case P_FADE:      pFade = value; break;
	case P_INVERT:    pInvert = value; break;
	case P_OFFSET:    pOffset = value; break;
	case P_RELOAD:
		if( value > 0.5f ) { fileStamp = -1; LoadData( true ); }
		break;
	default: return FF_FAIL;
	}
	return FF_SUCCESS;
}

float VJChaser::GetFloatParameter( unsigned int index )
{
	switch( index )
	{
	case P_SEQUENCE:  return pSequence;
	case P_STEPLEN:   return pStepLen;
	case P_DIRECTION: return pDirection;
	case P_MODE:      return pMode;
	case P_FADE:      return pFade;
	case P_INVERT:    return pInvert;
	case P_OFFSET:    return pOffset;
	}
	return 0.0f;
}
